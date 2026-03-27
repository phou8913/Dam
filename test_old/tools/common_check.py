"""
Shared helpers for connectivity test scripts.
"""

import os
import time
import uuid
from typing import Any, Dict

import requests


REAL_BASE_URL = "http://99.10.226.29:4560/api"
FAKE_BASE_URL = "http://127.0.0.1:5000/api"
FAKE_LOCALHOST_BASE_URL = "http://localhost:5000/api"


def classify_target(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized in {FAKE_BASE_URL.rstrip("/"), FAKE_LOCALHOST_BASE_URL.rstrip("/")}:
        return "fake"
    if normalized == REAL_BASE_URL.rstrip("/"):
        return "real"
    return "custom"


def choose_base_url() -> str:
    env_base_url = os.getenv("BASE_URL")
    if env_base_url:
        return env_base_url

    # Prefer the local fake server when it is reachable.
    try:
        response = requests.get("http://127.0.0.1:5000/health", timeout=1.0)
        if response.ok:
            return FAKE_BASE_URL
    except requests.RequestException:
        pass

    return REAL_BASE_URL


def result_payload(ok: bool, stage: str, **extra: Any) -> Dict[str, Any]:
    # Keep a small shared shape so all checks report results consistently.
    payload = {
        "ok": ok,
        "stage": stage,
        "timestamp": time.time(),
    }
    payload.update(extra)
    return payload


def build_reference(prefix: str) -> str:
    # Tag one request so downstream logs and results can be tied together.
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def build_rx_topic(application_id: str, device_id: str) -> str:
    return f"application/{application_id}/device/{device_id}/rx"


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
        return result_payload(
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
        return result_payload(
            True,
            "auth",
            url=url,
            status_code=response.status_code,
            elapsed_ms=elapsed_ms,
            token=token,
        )

    return result_payload(
        False,
        "auth",
        # Distinguish transport errors from successful HTTP responses with bad data.
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
    # The queued payload becomes the shared request for the full end-to-end check.
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
        return result_payload(
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
        return result_payload(
            True,
            "queue",
            url=url,
            status_code=response.status_code,
            elapsed_ms=elapsed_ms,
            request_payload=payload,
            response_body=body if body is not None else response.text,
        )

    return result_payload(
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
