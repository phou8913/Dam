"""Client -> server connectivity check."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from connectivity_common import classify_target


@dataclass
class ClientServerCheck:
    base_url: str
    account: str
    password: str
    device_id: str
    data_hex: str = "01"
    fport: int = 1
    reference: str = "connectivity-test"
    auth_timeout: float = 5.0
    queue_timeout: float = 10.0
    shared_auth_result: dict[str, Any] | None = None

    def finalize_with_queue(self, auth_result: dict[str, Any], queue_result: dict[str, Any], reference: str) -> dict[str, Any]:
        success = queue_result["ok"]
        request_payload = queue_result.get("request_payload") or {}
        return {
            "result": "PASS" if success else "FAIL",
            "stage": "client_server",
            "target": classify_target(self.base_url),
            "base_url": self.base_url,
            "device_id": self.device_id,
            "auth": {
                "ok": True,
                "status_code": auth_result.get("status_code"),
                "elapsed_ms": auth_result.get("elapsed_ms"),
            },
            "queue": queue_result,
            "reference": reference or request_payload.get("reference"),
        }

    @staticmethod
    def summarize(payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("result") == "NOT_RUN":
            return payload
        queue = payload.get("queue") or {}
        request_payload = queue.get("request_payload") or {}
        return {
            "result": payload.get("result"),
            "queue_ok": queue.get("ok"),
            "status_code": queue.get("status_code"),
            "reference": request_payload.get("reference"),
            "data_hex": request_payload.get("data"),
            "fport": request_payload.get("fPort"),
        }
