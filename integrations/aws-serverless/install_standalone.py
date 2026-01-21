#!/usr/bin/env python3
"""Standalone installation script for AWS Serverless Port integration.

Phases:
1. Port setup (blueprints, webhook, integration config)
2. Optional AWS deployment via CloudFormation

Required env vars:
  PORT_CLIENT_ID, PORT_CLIENT_SECRET

Flags:
  --port-only        Skip AWS deployment (prints CLI command)
  --verify-mappings  Diff live integration config vs local port-app-config.yml
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

try:
    import boto3
    import httpx
    import yaml
except ImportError:
    print("Error: Missing deps. Install: pip install boto3 httpx pyyaml", file=sys.stderr)
    sys.exit(1)

# Constants
SCRIPT_DIR = Path(__file__).resolve().parent
LOCAL_PORT_RESOURCES = SCRIPT_DIR / ".port" / "resources"
CLOUDFORMATION_TEMPLATE = SCRIPT_DIR / "cloudformation" / "aws-serverless.template"
MIN_WEBHOOK_ID_LENGTH = 10
HTTP_SUCCESS_THRESHOLD = 300

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s"
)
logger = logging.getLogger(__name__)


class PortSetupError(Exception):
    """Custom exception for Port setup errors."""
    pass


def load_env_file(env_file_path: Path) -> None:
    """Load environment variables from a .env file.

    Args:
        env_file_path: Path to the .env file

    Raises:
        PortSetupError: If env file doesn't exist
    """
    if not env_file_path.exists():
        raise PortSetupError(f"Env file not found: {env_file_path}")

    with open(env_file_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key.strip()] = value.strip().strip('"').strip("'")


def _load_config_file(filename: str, loader: callable) -> Any:
    """Generic config file loader."""
    path = LOCAL_PORT_RESOURCES / filename
    if not path.exists():
        raise FileNotFoundError(f"Missing {filename} at {path}")
    return loader(path.read_text())


def load_blueprints() -> list[dict[str, Any]]:
    """Load blueprints from JSON file."""
    return _load_config_file("blueprints.json", json.loads)


def load_port_app_config() -> dict[str, Any]:
    """Load Port app configuration from YAML file."""
    return _load_config_file("port-app-config.yml", yaml.safe_load)


def get_port_access_token(client_id: str, client_secret: str, base_url: str) -> str:
    """Obtain Port API access token.

    Args:
        client_id: Port client ID
        client_secret: Port client secret
        base_url: Port API base URL

    Returns:
        Access token string

    Raises:
        httpx.HTTPError: If authentication fails
    """
    url = f"{base_url.rstrip('/')}/v1/auth/access_token"
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            url,
            json={"clientId": client_id, "clientSecret": client_secret}
        )
        response.raise_for_status()
        return response.json()["accessToken"]


def normalize_webhook_identifier(value: str | None) -> str:
    """Extract webhook identifier from various input formats.

    Args:
        value: Webhook identifier, URL, or None

    Returns:
        Normalized webhook identifier
    """
    if not value:
        return "aws_ingest"

    if "/webhooks/" in value:
        parts = value.split("/webhooks/")
        if len(parts) > 1 and parts[1]:
            return parts[1].split("?")[0].split("/")[0]

    return value


def extract_webhook_key_from_response(data: dict[str, Any], ingest_base_url: str) -> str | None:
    """Extract webhook key or URL from API response."""
    base = ingest_base_url.rstrip('/')

    # Try direct URL fields first
    for path in ["url", "integration.url", "webhook.url"]:
        value = data
        for key in path.split('.'):
            value = value.get(key, {}) if isinstance(value, dict) else None
        if isinstance(value, str) and value.startswith(base):
            return value

    # Try key/ID fields
    for path in ["webhookKey", "integration.webhookKey", "webhook.webhookKey", "id", "_id"]:
        value = data
        for key in path.split('.'):
            value = value.get(key, {}) if isinstance(value, dict) else None
        if isinstance(value, str) and len(value) >= MIN_WEBHOOK_ID_LENGTH and value.isalnum():
            return f"{base}/{value}"

    return None


def resolve_existing_webhook(
    api_v1: str,
    headers: dict[str, str],
    identifier: str,
    ingest_base_url: str
) -> str | None:
    """Attempt to resolve existing webhook by identifier.

    Args:
        api_v1: API v1 base URL
        headers: HTTP headers for authentication
        identifier: Webhook identifier
        ingest_base_url: Base URL for webhook ingestion

    Returns:
        Webhook URL if found, None otherwise
    """
    get_url = f"{api_v1}/webhooks/{identifier}"
    logger.info(f"Checking for existing webhook: {identifier}...")

    with httpx.Client(timeout=30.0) as client:
        response = client.get(get_url, headers=headers)
        logger.debug(f"Webhook GET status={response.status_code}")
        logger.debug(f"Body: {response.text}")

        if response.status_code == 200:
            return extract_webhook_key_from_response(response.json(), ingest_base_url)

    return None


def create_webhook(
    api_v1: str,
    headers: dict[str, str],
    identifier: str,
    ingest_base_url: str
) -> str:
    """Create new webhook in Port.

    Args:
        api_v1: API v1 base URL
        headers: HTTP headers for authentication
        identifier: Webhook identifier
        ingest_base_url: Base URL for webhook ingestion

    Returns:
        Webhook URL

    Raises:
        PortSetupError: If webhook creation fails
    """
    body = {
        "identifier": identifier,
        "title": "AWS Serverless Webhook",
        "enabled": True,
        "security": {
            "secret": "",
            "signatureHeaderName": "",
            "signatureAlgorithm": "sha256",
            "signaturePrefix": "",
            "requestIdentifierPath": ""
        },
        "mappings": []
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.post(f"{api_v1}/webhooks", headers=headers, json=body)
        if response.status_code >= HTTP_SUCCESS_THRESHOLD:
            raise PortSetupError(
                f"Failed to create webhook: {response.status_code} {response.text}"
            )

        webhook_url = extract_webhook_key_from_response(response.json(), ingest_base_url)
        if not webhook_url:
            raise PortSetupError("Created webhook but ID not found in response")

        return webhook_url


def create_or_resolve_port_webhook(
    base_url: str,
    token: str,
    integration_id: str,
    webhook_opt: str | None,
    ingest_base_url: str
) -> str:
    """Create or resolve Port webhook for integration.

    Args:
        base_url: Port API base URL
        token: Access token
        integration_id: Integration identifier
        webhook_opt: Optional webhook identifier or URL
        ingest_base_url: Base URL for webhook ingestion

    Returns:
        Webhook URL

    Raises:
        PortSetupError: If webhook cannot be created or resolved
    """
    api_v1 = f"{base_url.rstrip('/')}/v1"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Handle direct URL or ID input
    if webhook_opt:
        if webhook_opt.startswith(("http://", "https://")):
            if webhook_opt.startswith(ingest_base_url.rstrip('/')):
                return webhook_opt
            return f"{ingest_base_url.rstrip('/')}/{webhook_opt.rstrip('/').split('/')[-1]}"

        if len(webhook_opt) >= MIN_WEBHOOK_ID_LENGTH and webhook_opt.isalnum():
            return f"{ingest_base_url.rstrip('/')}/{webhook_opt}"

    # Try to resolve existing webhook
    identifier = normalize_webhook_identifier(webhook_opt)
    webhook_url = resolve_existing_webhook(api_v1, headers, identifier, ingest_base_url)

    if webhook_url:
        return webhook_url

    # Create new webhook if not found
    return create_webhook(api_v1, headers, identifier, ingest_base_url)


def ensure_blueprints_exist(
    api_v1: str,
    headers: dict[str, str],
    blueprints: list[dict[str, Any]]
) -> None:
    """Ensure all blueprints exist in Port.

    Args:
        api_v1: API v1 base URL
        headers: HTTP headers for authentication
        blueprints: List of blueprint configurations
    """
    logger.info("\nCreating/updating blueprints...")

    with httpx.Client(timeout=30.0) as client:
        for blueprint in blueprints:
            identifier = blueprint.get("identifier")
            if not identifier:
                logger.warning("  Skipping blueprint without identifier")
                continue

            logger.info(f"  Ensuring blueprint '{identifier}' exists...")

            # Check if exists
            response = client.get(f"{api_v1}/blueprints/{identifier}", headers=headers)
            if response.status_code == 200:
                logger.info("    Exists")
                continue

            # Create blueprint
            response = client.post(
                f"{api_v1}/blueprints",
                headers=headers,
                json=blueprint
            )
            if response.status_code >= HTTP_SUCCESS_THRESHOLD:
                logger.error(f"    Failed: {response.status_code} {response.text}")
            else:
                logger.info("    Created")


def update_integration_config(
    client: httpx.Client,
    integ_url: str,
    headers: dict[str, str],
    port_app_config: dict[str, Any],
    integration_id: str,
    api_v1: str,
    force_recreate: bool
) -> None:
    """Update integration configuration with retry strategies.

    Args:
        client: HTTP client
        integ_url: Integration URL
        headers: HTTP headers
        port_app_config: Port app configuration
        integration_id: Integration identifier
        api_v1: API v1 base URL
        force_recreate: Whether to force recreation if update fails
    """
    response = client.get(integ_url, headers=headers)

    if response.status_code == 404:
        _create_integration(client, api_v1, headers, integration_id, port_app_config)
        return

    if response.status_code != 200:
        logger.error(f"  Unexpected response: {response.status_code} {response.text}")
        return

    # Update existing integration
    logger.info("  Integration exists, updating config...")
    live_data = response.json()
    patch_body = live_data.copy()
    patch_body["config"] = port_app_config

    # Remove read-only fields
    for field in ["createdAt", "updatedAt", "ok"]:
        patch_body.pop(field, None)

    response = client.patch(integ_url, headers=headers, json=patch_body)
    if response.status_code >= HTTP_SUCCESS_THRESHOLD:
        logger.error(f"  Patch failed: {response.status_code} {response.text}")
    else:
        logger.info("  Updated integration config")

    # Verify update and retry if needed
    if force_recreate and not _verify_config_present(client, integ_url, headers):
        _retry_config_update(
            client, integ_url, headers, port_app_config, integration_id, api_v1
        )


def _create_integration(
    client: httpx.Client,
    api_v1: str,
    headers: dict[str, str],
    integration_id: str,
    port_app_config: dict[str, Any]
) -> None:
    """Create new integration."""
    logger.info("  Creating integration...")
    body = {
        "installationId": integration_id,
        "installationAppType": "aws-serverless",
        "version": "1.0.0",
        "changelogDestination": {},
        "config": port_app_config,
    }

    response = client.post(f"{api_v1}/integration", headers=headers, json=body)
    if response.status_code >= HTTP_SUCCESS_THRESHOLD:
        logger.error(f"  Create failed: {response.status_code} {response.text}")
    else:
        logger.info("  Created integration")


def _verify_config_present(
    client: httpx.Client,
    integ_url: str,
    headers: dict[str, str]
) -> bool:
    """Check if integration config has resources."""
    response = client.get(integ_url, headers=headers)
    if response.status_code != 200:
        return False

    data = response.json()
    # Response wraps integration in .integration property
    if "integration" in data:
        config = data["integration"].get("config")
    else:
        config = data.get("config")

    if not isinstance(config, dict):
        return False

    resources = config.get("resources")
    return bool(resources)


def _retry_config_update(
    client: httpx.Client,
    integ_url: str,
    headers: dict[str, str],
    port_app_config: dict[str, Any],
    integration_id: str,
    api_v1: str
) -> None:
    """Retry configuration update using alternative methods."""
    logger.info("  Live config still empty; attempting subresource PATCH...")

    # Try subresource PATCH
    sub_url = f"{integ_url}/config"
    response = client.patch(sub_url, headers=headers, json=port_app_config)

    if response.status_code < HTTP_SUCCESS_THRESHOLD:
        logger.info("  Subresource config PATCH succeeded; verifying...")
        if _verify_config_present(client, integ_url, headers):
            logger.info("  ✓ Config now present after subresource PATCH")
            return

    # Fall back to delete and recreate
    logger.info("  Config still empty after subresource PATCH; recreating integration...")

    response = client.delete(integ_url, headers=headers)
    if response.status_code >= HTTP_SUCCESS_THRESHOLD:
        logger.error(f"  Delete failed: {response.status_code} {response.text}")
        return

    _create_integration(client, api_v1, headers, integration_id, port_app_config)
    logger.info("  ✓ Integration recreated with config")


def _apply_webhook_mappings(api_v1: str, headers: dict, webhook_id: str) -> None:
    """Apply webhook mappings for EventBridge events.

    Args:
        api_v1: Port API v1 URL
        headers: Request headers with auth token
        webhook_id: Webhook identifier
    """
    if not webhook_id:
        logger.warning("No webhook identifier provided, skipping mappings")
        return

    mappings_url = f"{api_v1}/webhooks/{webhook_id}/mapping"

    # EventBridge event mappings
    mappings = {
        "resources": [
            {
                "kind": "ec2_instance",
                "selector": {"query": '.source == "aws.ec2"'},
                "port": {
                    "entity": {
                        "mappings": {
                            "identifier": ".detail.instance_id",
                            "title": ".detail.instance_type",
                            "properties": {
                                "state": ".detail.state",
                                "availability_zone": ".detail.availability_zone"
                            }
                        }
                    }
                }
            }
        ]
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(mappings_url, json=mappings, headers=headers)
            response.raise_for_status()
            logger.info(f"Applied webhook mappings for {webhook_id}")
    except httpx.HTTPError as e:
        logger.error(f"Failed to apply webhook mappings: {e}")


def setup_port_resources(
    client_id: str,
    client_secret: str,
    base_url: str,
    integration_id: str,
    webhook_opt: str | None,
    ingest_base_url: str,
    force_recreate: bool = False
) -> str:
    """Set up Port resources (blueprints, webhook, integration).

    Args:
        client_id: Port client ID
        client_secret: Port client secret
        base_url: Port API base URL
        integration_id: Integration identifier
        webhook_opt: Optional webhook identifier
        ingest_base_url: Webhook ingest base URL
        force_recreate: Force recreation if config update fails

    Returns:
        Webhook URL
    """
    token = get_port_access_token(client_id, client_secret, base_url)
    api_v1 = f"{base_url.rstrip('/')}/v1"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    logger.info("\nLoading blueprints and config from local .port/resources...")
    blueprints = load_blueprints()
    port_app_config = load_port_app_config()

    ensure_blueprints_exist(api_v1, headers, blueprints)

    webhook_url = create_or_resolve_port_webhook(
        base_url, token, integration_id, webhook_opt, ingest_base_url
    )

    # Apply webhook mappings for EventBridge events
    _apply_webhook_mappings(
        api_v1, headers, normalize_webhook_identifier(webhook_opt)
    )

    logger.info(f"\nSetting up integration '{integration_id}'...")
    integ_url = f"{api_v1}/integration/{integration_id}"

    with httpx.Client(timeout=30.0) as client:
        update_integration_config(
            client, integ_url, headers, port_app_config,
            integration_id, api_v1, force_recreate
        )

    return webhook_url


def verify_mappings(
    client_id: str,
    client_secret: str,
    base_url: str,
    integration_id: str
) -> None:
    """Verify integration mappings match local configuration.

    Args:
        client_id: Port client ID
        client_secret: Port client secret
        base_url: Port API base URL
        integration_id: Integration identifier
    """
    logger.info("\nVerifying integration mappings (local vs live)...")

    try:
        token = get_port_access_token(client_id, client_secret, base_url)
        api_v1 = f"{base_url.rstrip('/')}/v1"
        integ_url = f"{api_v1}/integration/{integration_id}"

        with httpx.Client(timeout=30.0) as client:
            response = client.get(integ_url, headers={"Authorization": f"Bearer {token}"})

            if response.status_code != 200:
                logger.error(
                    f"  ERROR: Failed to fetch live integration: "
                    f"{response.status_code} {response.text}"
                )
                return

            live_cfg = response.json().get("config", {})
            local_cfg_full = load_port_app_config()

            diffs = _compare_configs(live_cfg, local_cfg_full)

            if not diffs:
                logger.info("  ✓ Live mappings match local configuration")
            else:
                logger.info("  Mapping differences:")
                for diff in diffs:
                    logger.info(f"    - {diff}")

    except Exception as e:
        logger.warning(f"  WARN: Mapping verification failed: {type(e).__name__}: {e}")


def _compare_configs(live_cfg: dict[str, Any], local_cfg: dict[str, Any]) -> list[str]:
    """Compare live and local configurations.

    Args:
        live_cfg: Live configuration from Port
        local_cfg: Local configuration from file

    Returns:
        List of difference descriptions
    """
    live_resources = live_cfg.get("resources") or []
    local_resources = local_cfg.get("resources") or []

    def index_by_kind(resources: list[dict]) -> dict[str, dict]:
        return {r.get("kind"): r for r in resources if r.get("kind")}

    live_idx = index_by_kind(live_resources)
    local_idx = index_by_kind(local_resources)

    diffs = []
    all_kinds = sorted(set(live_idx) | set(local_idx))

    for kind in all_kinds:
        local_resource = local_idx.get(kind)
        live_resource = live_idx.get(kind)

        if not live_resource:
            diffs.append(f"MISSING in live: {kind}")
            continue

        if not local_resource:
            diffs.append(f"EXTRA in live: {kind}")
            continue

        # Compare mappings
        def get_mappings(resource: dict) -> dict:
            return resource.get("port", {}).get("entity", {}).get("mappings", {})

        local_mappings = get_mappings(local_resource)
        live_mappings = get_mappings(live_resource)

        diffs.extend(_compare_mapping_fields(kind, local_mappings, live_mappings))
        diffs.extend(_compare_properties(kind, local_mappings, live_mappings))
        diffs.extend(_compare_relations(kind, local_mappings, live_mappings))

    return diffs


def _compare_mapping_fields(
    kind: str,
    local_mappings: dict,
    live_mappings: dict
) -> list[str]:
    """Compare mapping fields between local and live."""
    diffs = []
    for field in ["identifier", "title", "blueprint"]:
        if local_mappings.get(field) != live_mappings.get(field):
            diffs.append(
                f"DIFF {kind} {field}: "
                f"live={live_mappings.get(field)} local={local_mappings.get(field)}"
            )
    return diffs


def _compare_properties(
    kind: str,
    local_mappings: dict,
    live_mappings: dict
) -> list[str]:
    """Compare properties between local and live."""
    local_props = local_mappings.get("properties", {}) or {}
    live_props = live_mappings.get("properties", {}) or {}

    diffs = []
    for key in local_props.keys() - live_props.keys():
        diffs.append(f"MISSING property in live {kind}.{key}")

    for key in live_props.keys() - local_props.keys():
        diffs.append(f"EXTRA property in live {kind}.{key}")

    for key in local_props.keys() & live_props.keys():
        if local_props[key] != live_props[key]:
            diffs.append(
                f"DIFF property {kind}.{key}: "
                f"live={live_props[key]} local={local_props[key]}"
            )

    return diffs


def _compare_relations(
    kind: str,
    local_mappings: dict,
    live_mappings: dict
) -> list[str]:
    """Compare relations between local and live."""
    local_rels = local_mappings.get("relations", {}) or {}
    live_rels = live_mappings.get("relations", {}) or {}

    diffs = []
    for key in local_rels.keys() - live_rels.keys():
        diffs.append(f"MISSING relation in live {kind}.{key}")

    for key in live_rels.keys() - local_rels.keys():
        diffs.append(f"EXTRA relation in live {kind}.{key}")

    for key in local_rels.keys() & live_rels.keys():
        if local_rels[key] != live_rels[key]:
            diffs.append(
                f"DIFF relation {kind}.{key}: "
                f"live={live_rels[key]} local={local_rels[key]}"
            )

    return diffs


def deploy_cloudformation_stack(
    stack_name: str,
    region: str,
    webhook_url: str,
    queue_name: str,
    lambda_name: str,
    event_sources: str
) -> dict[str, str]:
    """Deploy CloudFormation stack for AWS resources.

    Args:
        stack_name: CloudFormation stack name
        region: AWS region
        webhook_url: Port webhook URL
        queue_name: SQS queue name
        lambda_name: Lambda function name
        event_sources: Comma-separated event sources

    Returns:
        Stack outputs dictionary

    Raises:
        PortSetupError: If deployment fails
    """
    logger.info(f"\nDeploying CloudFormation stack '{stack_name}' in {region}...")

    if not CLOUDFORMATION_TEMPLATE.exists():
        raise PortSetupError(f"Missing template {CLOUDFORMATION_TEMPLATE}")

    template_body = CLOUDFORMATION_TEMPLATE.read_text()
    cf_client = boto3.client("cloudformation", region_name=region)

    params = [
        {"ParameterKey": "QueueName", "ParameterValue": queue_name},
        {"ParameterKey": "LambdaFunctionName", "ParameterValue": lambda_name},
        {"ParameterKey": "PortWebhookUrl", "ParameterValue": webhook_url},
        {"ParameterKey": "SupportedEventSources", "ParameterValue": event_sources},
    ]

    try:
        stack_exists = _check_stack_exists(cf_client, stack_name)

        if stack_exists:
            _update_stack(cf_client, stack_name, template_body, params)
        else:
            _create_stack(cf_client, stack_name, template_body, params)

        stack = cf_client.describe_stacks(StackName=stack_name)["Stacks"][0]
        outputs = {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}

        logger.info("\n✓ Stack deployment completed successfully")
        return outputs

    except Exception as e:
        raise PortSetupError(f"CloudFormation failed: {type(e).__name__}: {e}")


def _check_stack_exists(cf_client: Any, stack_name: str) -> bool:
    """Check if CloudFormation stack exists."""
    try:
        cf_client.describe_stacks(StackName=stack_name)
        return True
    except cf_client.exceptions.ClientError as e:
        if "does not exist" in str(e):
            return False
        raise


def _update_stack(
    cf_client: Any,
    stack_name: str,
    template_body: str,
    params: list[dict]
) -> None:
    """Update existing CloudFormation stack."""
    logger.info("  Updating existing stack...")

    try:
        cf_client.update_stack(
            StackName=stack_name,
            TemplateBody=template_body,
            Parameters=params,
            Capabilities=["CAPABILITY_NAMED_IAM"]
        )
        waiter = cf_client.get_waiter("stack_update_complete")
        logger.info("  Waiting for update to complete...")
        waiter.wait(StackName=stack_name)
    except cf_client.exceptions.ClientError as e:
        if "No updates are to be performed" in str(e):
            logger.info("  No updates required")
        else:
            raise


def _create_stack(
    cf_client: Any,
    stack_name: str,
    template_body: str,
    params: list[dict]
) -> None:
    """Create new CloudFormation stack."""
    logger.info("  Creating new stack...")

    cf_client.create_stack(
        StackName=stack_name,
        TemplateBody=template_body,
        Parameters=params,
        Capabilities=["CAPABILITY_NAMED_IAM"]
    )
    waiter = cf_client.get_waiter("stack_create_complete")
    logger.info("  Waiting for creation to complete...")
    waiter.wait(StackName=stack_name)


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments.

    Returns:
        Parsed arguments
    """
    parser = argparse.ArgumentParser(
        description="Install AWS Serverless Port integration"
    )

    parser.add_argument(
        "--env-file",
        type=Path,
        help="Path to .env file with PORT_CLIENT_ID and PORT_CLIENT_SECRET"
    )
    parser.add_argument(
        "--port-base-url",
        default="https://api.getport.io",
        help="Port API base URL"
    )
    parser.add_argument(
        "--ingest-base-url",
        default=os.environ.get("PORT_INGEST_BASE_URL", "https://ingest.getport.io"),
        help="Port ingest base URL fallback if webhook URL not returned"
    )
    parser.add_argument(
        "--aws-region",
        default="us-east-1",
        help="AWS region for deployment"
    )
    parser.add_argument(
        "--integration-id",
        default="aws-serverless",
        help="Integration identifier in Port"
    )
    parser.add_argument(
        "--stack-name",
        default="port-aws-serverless",
        help="CloudFormation stack name"
    )
    parser.add_argument(
        "--queue-name",
        default="port-aws-events-queue",
        help="SQS queue name"
    )
    parser.add_argument(
        "--lambda-function-name",
        default="port-aws-event-processor",
        help="Lambda function name"
    )
    parser.add_argument(
        "--webhook",
        default=None,
        help="Webhook identifier, full URL, or partial URL (default: aws_ingest)"
    )
    parser.add_argument(
        "--event-sources",
        default="aws.ec2,aws.s3,aws.ecs",
        help="Comma-separated AWS event sources for EventBridge rule"
    )
    parser.add_argument(
        "--port-only",
        action="store_true",
        help="Run only Port setup, print AWS CLI for CloudFormation"
    )
    parser.add_argument(
        "--force-recreate",
        action="store_true",
        help="Delete and recreate integration with local config if update fails"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate all actions, print what would happen"
    )
    parser.add_argument(
        "--verify-mappings",
        action="store_true",
        help="After Port setup, diff live integration config vs local port-app-config.yml"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )

    return parser.parse_args()


def print_banner() -> None:
    """Print installation banner."""
    print("=" * 70)
    print("AWS Serverless Port Integration - Standalone Installation")
    print("=" * 70)


def validate_credentials() -> tuple[str, str]:
    """Validate required credentials are present.

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        PortSetupError: If credentials are missing
    """
    client_id = os.environ.get("PORT_CLIENT_ID")
    client_secret = os.environ.get("PORT_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise PortSetupError(
            "PORT_CLIENT_ID and PORT_CLIENT_SECRET must be set\n"
            "       Set them as environment variables or use --env-file"
        )

    return client_id, client_secret


def print_configuration(args: argparse.Namespace) -> None:
    """Print current configuration."""
    config = [
        ("Port Base URL", args.port_base_url),
        ("Integration ID", args.integration_id),
        ("AWS Region", args.aws_region),
        ("Stack Name", args.stack_name),
        ("Queue Name", args.queue_name),
        ("Lambda Function", args.lambda_function_name),
        ("Webhook", args.webhook or 'aws_ingest'),
        ("Ingest Base URL (fallback)", args.ingest_base_url),
        ("Event Sources", args.event_sources)
    ]
    logger.info("\nConfiguration:")
    for label, value in config:
        logger.info(f"  {label}: {value}")


def print_summary(
    args: argparse.Namespace,
    webhook_url: str,
    outputs: dict[str, str] | None
) -> None:
    """Print installation summary.

    Args:
        args: Parsed arguments
        webhook_url: Webhook URL
        outputs: CloudFormation outputs (if deployed)
    """
    logger.info("\n" + "=" * 70)
    logger.info("INSTALLATION COMPLETE")
    logger.info("=" * 70)
    logger.info("\nPort Resources:")
    logger.info(f"  Integration ID: {args.integration_id}")
    logger.info(f"  Webhook URL: {webhook_url}")
    logger.info("\nAWS Resources:")
    logger.info(f"  Region: {args.aws_region}")
    logger.info(f"  Stack Name: {args.stack_name}")

    if outputs:
        for key, value in outputs.items():
            logger.info(f"  {key}: {value}")

    logger.info("\nThe integration is now active and will route AWS events to Port.")
    logger.info("=" * 70)


def main() -> None:
    """Main entry point."""
    try:
        print_banner()
        args = parse_arguments()

        # Configure logging
        if args.debug:
            logging.getLogger().setLevel(logging.DEBUG)

        # Load environment file if specified
        if args.env_file:
            logger.info(f"Loading environment variables from: {args.env_file}")
            load_env_file(args.env_file)

        # Validate credentials
        client_id, client_secret = validate_credentials()

        print_configuration(args)

        # Step 1: Port setup
        logger.info("\n" + "=" * 70)
        logger.info("STEP 1: Setting up Port resources")
        logger.info("=" * 70)

        if args.dry_run:
            logger.info(
                "[DRY-RUN] Would set up Port resources "
                "(blueprints, webhook, integration config)"
            )
            webhook_url = "<simulated-webhook-url>"
        else:
            webhook_url = setup_port_resources(
                client_id,
                client_secret,
                args.port_base_url,
                args.integration_id,
                args.webhook,
                args.ingest_base_url,
                force_recreate=args.force_recreate
            )
            logger.info(f"\n✓ Port setup complete. Webhook URL: {webhook_url}")

            if args.verify_mappings:
                verify_mappings(
                    client_id,
                    client_secret,
                    args.port_base_url,
                    args.integration_id
                )

        # Step 2: AWS deployment
        logger.info("\n" + "=" * 70)
        logger.info("STEP 2: Deploying AWS infrastructure")
        logger.info("=" * 70)

        cf_cli = (
            f"aws cloudformation deploy "
            f"--stack-name {args.stack_name} "
            f"--template-file cloudformation/aws-serverless.template "
            f"--region {args.aws_region} "
            f"--capabilities CAPABILITY_NAMED_IAM "
            f"--parameter-overrides "
            f"QueueName={args.queue_name} "
            f"LambdaFunctionName={args.lambda_function_name} "
            f"PortWebhookUrl={webhook_url} "
            f'SupportedEventSources="{args.event_sources}"'
        )

        outputs = None
        if args.dry_run:
            logger.info("[DRY-RUN] Would run CloudFormation deployment:")
            logger.info(cf_cli)
        elif args.port_only:
            logger.info("Port setup complete. To deploy AWS resources, run:")
            logger.info(cf_cli)
        else:
            outputs = deploy_cloudformation_stack(
                args.stack_name,
                args.aws_region,
                webhook_url,
                args.queue_name,
                args.lambda_function_name,
                args.event_sources,
            )

        print_summary(args, webhook_url, outputs)

    except PortSetupError as e:
        logger.error(f"\nERROR: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("\n\nInterrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"\nUnexpected error: {type(e).__name__}: {e}")
        if args.debug:
            raise
        sys.exit(1)


if __name__ == "__main__":
    main()
