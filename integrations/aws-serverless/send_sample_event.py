#!/usr/bin/env python3
"""Send an AWS event payload to a webhook for testing.

Usage:
    python send_sample_event.py <webhook_url> <event_file.json>
"""

import argparse
import json
from pathlib import Path

import httpx


def load_event(path: Path) -> dict:
    """Load an event payload from a JSON file."""
    if not path.exists():
        raise FileNotFoundError(f"Event file not found: {path}")
    return json.loads(path.read_text())


def send_event(webhook_url: str, event: dict) -> None:
    """Send an event payload to the webhook."""
    print(f"\nSending event to {webhook_url}...")
    print(f"Event payload: {json.dumps(event, indent=2)}\n")

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(webhook_url, json=event)
            print(f"Response: {response.status_code}")
            if response.text:
                print(f"Body: {response.text}")
            if response.status_code >= 400:
                print(f"\n⚠️  Request failed with status {response.status_code}")
                raise SystemExit(1)
            print("\n✓ Event sent successfully")
    except httpx.RequestError as exc:
        print(f"\n✗ Request failed: {exc}")
        raise SystemExit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send a JSON event payload to a Port webhook")
    parser.add_argument("webhook_url", help="Full webhook URL (e.g., https://ingest.getport.io/<id>)")
    parser.add_argument("event_file", type=Path, help="Path to JSON file containing the event payload")
    return parser.parse_args()


def main() -> None:
    """Send a sample AWS event to a Port webhook for testing."""
    args = parse_args()

    try:
        event = load_event(args.event_file)
    except FileNotFoundError as exc:
        print(f"✗ Error: {exc}")
        raise SystemExit(1)
    except json.JSONDecodeError as exc:
        print(f"✗ Invalid JSON in {args.event_file}: {exc}")
        raise SystemExit(1)

    print("=" * 70)
    print("AWS Event Sender")
    print("=" * 70)
    print(f"Webhook URL: {args.webhook_url}")
    print(f"Event File:   {args.event_file}")
    print("=" * 70)

    send_event(args.webhook_url, event)


if __name__ == "__main__":
    main()
