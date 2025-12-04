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

    with httpx.Client(timeout=10.0) as client:
        response = client.post(webhook_url, json=event)
        print(f"Response: {response.status_code}")
        if response.text:
            print(f"Body: {response.text}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send a JSON event payload to a Port webhook")
    parser.add_argument("webhook_url", help="Full webhook URL (e.g., https://ingest.getport.io/<id>)")
    parser.add_argument("event_file", type=Path, help="Path to JSON file containing the event payload")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    event = load_event(args.event_file)

    print("=" * 70)
    print("AWS Event Sender")
    print("=" * 70)
    print(f"Webhook URL: {args.webhook_url}")
    print(f"Event File:   {args.event_file}")
    print("=" * 70)

    send_event(args.webhook_url, event)


if __name__ == "__main__":
    main()
