"""Lambda handler to process SQS records and forward to Port webhook.

This handler mirrors the inline function used in the CloudFormation template but
is provided here for development and local testing. The Lambda in CF can be updated
to load a deployment package with this file instead of the inline ZipFile.
"""

import json
import logging
import os
import time
from urllib import request

logger = logging.getLogger()
logger.setLevel(logging.INFO)

PORT_WEBHOOK = os.environ.get("PORT_WEBHOOK_URL")


def post_to_port(body_bytes: bytes, headers: dict[str, str]) -> tuple[int, str]:
    req = request.Request(PORT_WEBHOOK, data=body_bytes, headers=headers, method="POST")
    with request.urlopen(req, timeout=10) as resp:
        return resp.getcode(), resp.read().decode("utf-8")


def _build_minimal_entity_from_event(payload: dict) -> dict:
    """Create a minimal Port entity shape when incoming payload is not already an entity.

    We try to populate sensible identifier and title fields. This is intentionally simple:
    the preferred mode is to have aws-v3 produce fully-formed entities and the Lambda will
    pass them through unchanged.
    """
    # Try common candidates for identifier
    identifier = None
    # EventBridge-style detail that may contain resource identifiers
    if isinstance(payload.get("detail"), dict):
        detail = payload.get("detail")
        identifier = detail.get("resource") or detail.get("requestParameters", {}).get("bucketName")
        if not identifier:
            identifier = payload.get("id") or payload.get("detail", {}).get("arn")
    identifier = identifier or payload.get("id") or f"aws-event-{int(time.time()*1000)}"

    title = payload.get("detail-type") or payload.get("source") or identifier

    entity = {
        "identifier": identifier,
        "title": title,
        "blueprint": "awsEvent",
        "properties": {"event": payload},
    }
    return entity


def lambda_handler(event, context):
    logger.info("Received event with %d records", len(event.get("Records", [])))
    for rec in event.get("Records", []):
        body = rec.get("body")
        if not body:
            continue
        try:
            payload = json.loads(body)
        except Exception:
            # non-json bodies are preserved as raw string under properties
            payload = {"raw": body}

        # If the payload already matches the Port aws-v3 entity shape, forward as-is.
        if isinstance(payload, dict) and "blueprint" in payload and "identifier" in payload:
            entity = payload
        else:
            entity = _build_minimal_entity_from_event(payload)

        body_bytes = json.dumps(entity).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        try:
            status, resp_text = post_to_port(body_bytes, headers)
            logger.info("Posted entity to Port, status=%s, identifier=%s", status, entity.get("identifier"))
        except Exception:
            logger.exception("Failed to post record to Port")
