"""Setup script for AWS Serverless integration resources in Port.

This script will:
- Upload blueprints from the aws-v3 integration to Port
- Apply the port-app-config.yml mapping to the integration installation

Environment variables expected:
- PORT_API_TOKEN: full bearer token, e.g. 'Bearer ey...'
- PORT_BASE_URL: base URL for Port (e.g. https://app.port.dev or https://api.port.example). Must not include /v1
- INTEGRATION_IDENTIFIER: identifier to use for the integration installation (default: aws-serverless)
- INTEGRATION_TYPE: integration type (default: aws-serverless)
- INTEGRATION_VERSION: integration version string (default: 1.0.0)

This is a pragmatic, lightweight script that uses the Port HTTP endpoints directly with the
authorization token provided in PORT_API_TOKEN. It is intentionally small and does not rely on
Ocean runtime. It attempts to create blueprints if they are missing and will create/patch the
integration config with the provided port-app-config.yml.
"""

import json
import os
import sys
from pathlib import Path

import httpx
import yaml


ROOT = Path(__file__).resolve().parent.parent
AWS_V3_PORT_RESOURCES = (
    ROOT
    / "integrations"
    / "aws-v3"
    / ".port"
    / "resources"
)


def load_blueprints() -> list[dict]:
    path = AWS_V3_PORT_RESOURCES / "blueprints.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing blueprints.json at {path}")
    return json.loads(path.read_text())


def load_port_app_config() -> dict:
    path = AWS_V3_PORT_RESOURCES / "port-app-config.yml"
    if not path.exists():
        raise FileNotFoundError(f"Missing port-app-config.yml at {path}")
    return yaml.safe_load(path.read_text())


def get_env(name: str, default: str | None = None) -> str:
    val = os.environ.get(name, default)
    if val is None:
        print(f"Required environment variable {name} not set", file=sys.stderr)
        sys.exit(2)
    return val


def main() -> None:
    token = get_env("PORT_API_TOKEN")
    base_url = get_env("PORT_BASE_URL")
    integration_identifier = os.environ.get("INTEGRATION_IDENTIFIER", "aws-serverless")
    integration_type = os.environ.get("INTEGRATION_TYPE", "aws-serverless")
    integration_version = os.environ.get("INTEGRATION_VERSION", "1.0.0")

    api_v1 = base_url.rstrip("/") + "/v1"

    headers = {"Authorization": token, "Content-Type": "application/json"}

    client = httpx.Client(timeout=30.0)

    # Load resources
    print("Loading blueprints and port-app-config from aws-v3 integration resources...")
    blueprints = load_blueprints()
    port_app_config = load_port_app_config()

    # Create blueprints
    for bp in blueprints:
        identifier = bp.get("identifier")
        if not identifier:
            print("Skipping blueprint without identifier")
            continue
        print(f"Ensuring blueprint {identifier} exists...")
        # Check if blueprint exists
        get_url = f"{api_v1}/blueprints/{identifier}"
        r = client.get(get_url, headers=headers)
        if r.status_code == 200:
            print(f" - blueprint {identifier} already exists, skipping")
            continue
        if r.status_code not in (404,):
            print(f" - unexpected result checking blueprint {identifier}: {r.status_code} {r.text}")
        # Create
        create_url = f"{api_v1}/blueprints"
        r = client.post(create_url, headers=headers, json=bp)
        if r.status_code >= 300:
            print(f"Failed to create blueprint {identifier}: {r.status_code} {r.text}", file=sys.stderr)
        else:
            print(f" - created blueprint {identifier}")

    # Create or patch integration with port-app-config
    integration_url = f"{api_v1}/integration/{integration_identifier}"
    r = client.get(integration_url, headers=headers)
    if r.status_code == 200:
        print(f"Integration {integration_identifier} exists. Patching config...")
        patch_body = {"config": port_app_config, "version": integration_version}
        r = client.patch(integration_url, headers=headers, json=patch_body)
        if r.status_code >= 300:
            print(f"Failed to patch integration: {r.status_code} {r.text}", file=sys.stderr)
        else:
            print("Patched integration config successfully")
    elif r.status_code == 404:
        print(f"Integration {integration_identifier} not found. Creating...")
        create_url = f"{api_v1}/integration"
        body = {
            "installationId": integration_identifier,
            "installationAppType": integration_type,
            "version": integration_version,
            "changelogDestination": {},
            "config": port_app_config,
        }
        r = client.post(create_url, headers=headers, json=body)
        if r.status_code >= 300:
            print(f"Failed to create integration: {r.status_code} {r.text}", file=sys.stderr)
        else:
            print("Created integration successfully")
    else:
        print(f"Unexpected response checking integration: {r.status_code} {r.text}", file=sys.stderr)


if __name__ == "__main__":
    main()
