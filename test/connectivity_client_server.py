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
import time
from typing import Any, Dict

import requests


REAL_BASE_URL = "http://99.10.226.29:4560/api"
FAKE_BASE_URL = "http://localhost:5000/api"
DEFAULT_ACCOUNT = os.getenv("LORA_ACCOUNT", "admin")
DEFAULT_PASSWORD = os.getenv("LORA_PASSWORD", "admin")
DEFAULT_DEVICE_ID = os.getenv("DEVICE_ID", "8695311000942380")


def classify_target(base_url: str) -> str:
    if base_url.rstrip("/") == FAKE_BASE_URL.rstrip("/"):
        return "fake"
    if base_url.rstrip("/") == REAL_BASE_URL.rstrip("/"):
        return "real"
    return "custom"


def choose_base_url() -> str:
    env_base_url = os.getenv("BASE_URL")
    if env_base_url:
        return env_base_url

    try:
        response = requests.get("http://localhost:5000/health", timeout=1.0)
        if response.ok:
            return FAKE_BASE_URL
    except requests.RequestException:
        pass

    return REAL_BASE_URL


DEFAULT_BASE_URL = choose_base_url()


def _result(ok: bool, stage: str, **extra: Any) -> Dict[str, Any]:
    payload = {
        "ok": ok,
        "stage": stage,
        "timestamp": time.time(),
    }
    payload.update(extra)
    return payload


def authenticate(base_url: str, account: str, password: str, timeout: float) -> Dict[str, Any]:
    url = f"{base_url}/v1/internal/auth"
    started = time.time()
    try:
        response = requests.post(
            url,
            json={"account": account, "password": password},
            timeout=timeout,
        )
        elapsed_ms = round((time.time() - started) * 1000, 2)
    except requests.RequestException as exc:
        return _result(
            False,
            "auth",
            error_type="NETWORK_FAIL",
            error_message=str(exc),
            url=url,
        )

    try:
        body = response.json()
    except ValueError:
        body = None

    token = body.get("token") if isinstance(body, dict) else None
    if response.ok and token:
        return _result(
            True,
            "auth",
            url=url,
            status_code=response.status_code,
            elapsed_ms=elapsed_ms,
            token=token,
        )

    return _result(
        False,
        "auth",
        error_type="HTTP_FAIL" if not response.ok else "BAD_RESPONSE",
        error_message="Authentication failed" if not response.ok else "Authentication succeeded without token",
        url=url,
        status_code=response.status_code,
        elapsed_ms=elapsed_ms,
        response_body=body if body is not None else response.text,
    )


def queue_downlink(
    base_url: str,
    device_id: str,
    token: str,
    data_hex: str,
    fport: int,
    reference: str,
    timeout: float,
) -> Dict[str, Any]:
    url = f"{base_url}/v1/devices/{device_id}/queue"
    payload = {
        "confirmed": True,
        "mode": "hex",
        "data": data_hex,
        "fPort": fport,
        "reference": reference,
    }
    headers = {
        "token": token,
        "content-type": "application/json",
    }

    started = time.time()
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=timeout)
        elapsed_ms = round((time.time() - started) * 1000, 2)
    except requests.RequestException as exc:
        return _result(
            False,
            "queue",
            error_type="NETWORK_FAIL",
            error_message=str(exc),
            url=url,
            request_payload=payload,
        )

    try:
        body = response.json()
    except ValueError:
        body = None

    if response.ok:
        return _result(
            True,
            "queue",
            url=url,
            status_code=response.status_code,
            elapsed_ms=elapsed_ms,
            request_payload=payload,
            response_body=body if body is not None else response.text,
        )

    return _result(
        False,
        "queue",
        error_type="HTTP_FAIL",
        error_message="Queue submission failed",
        url=url,
        status_code=response.status_code,
        elapsed_ms=elapsed_ms,
        request_payload=payload,
        response_body=body if body is not None else response.text,
    )


def main() -> int:
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

    queue_result = queue_downlink(
        args.base_url,
        args.device_id,
        auth_result["token"],
        args.data_hex,
        args.fport,
        args.reference,
        args.queue_timeout,
    )
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
