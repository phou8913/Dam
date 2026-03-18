"""
Client -> server connectivity test for the real LoRa backend.

This script verifies only the HTTP leg used by the app:
1. Authenticate with /v1/internal/auth
2. Submit a downlink with /v1/devices/{device_id}/queue

If no BASE_URL is provided, it auto-selects the local fake server when
http://localhost:5000/health is reachable; otherwise it falls back to
the real backend.
"""

import argparse
import json
import os
import sys
from connectivity_common import authenticate, choose_base_url, classify_target, queue_downlink


DEFAULT_ACCOUNT = os.getenv("LORA_ACCOUNT", "admin")
DEFAULT_PASSWORD = os.getenv("LORA_PASSWORD", "admin")
DEFAULT_DEVICE_ID = os.getenv("DEVICE_ID", "8695311000942380")


DEFAULT_BASE_URL = choose_base_url()


def main() -> int:
    # Parse runtime parameters for the HTTP connectivity check.
    parser = argparse.ArgumentParser(description="Test client -> server HTTP connectivity")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--account", default=DEFAULT_ACCOUNT)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--device-id", default=DEFAULT_DEVICE_ID)
    parser.add_argument("--data-hex", default="01")
    parser.add_argument("--fport", type=int, default=1)
    parser.add_argument("--reference", default="connectivity-test")
    parser.add_argument("--auth-timeout", type=float, default=5.0)
    parser.add_argument("--queue-timeout", type=float, default=10.0)
    args = parser.parse_args()

    # Authenticate first to verify the client can access the real HTTP entry point.
    auth_result = authenticate(args.base_url, args.account, args.password, args.auth_timeout)
    if not auth_result["ok"]:
        print(json.dumps({
            "result": "FAIL",
            "stage": "client_server",
            "target": classify_target(args.base_url),
            "base_url": args.base_url,
            "device_id": args.device_id,
            "auth": auth_result,
        }, indent=2))
        return 1

    # Submit one minimal downlink request to verify the queue API is reachable.
    queue_result = queue_downlink(
        args.base_url,
        args.device_id,
        auth_result["token"],
        args.data_hex,
        args.fport,
        args.reference,
        args.queue_timeout,
    )

    # Report PASS only when the HTTP queue submission succeeds.
    success = queue_result["ok"]
    output = {
        "result": "PASS" if success else "FAIL",
        "stage": "client_server",
        "target": classify_target(args.base_url),
        "base_url": args.base_url,
        "device_id": args.device_id,
        "auth": {
            "ok": True,
            "status_code": auth_result.get("status_code"),
            "elapsed_ms": auth_result.get("elapsed_ms"),
        },
        "queue": queue_result,
    }
    print(json.dumps(output, indent=2))
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
