"""Client -> server connectivity check."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from .connectivity_common import authenticate, classify_target, queue_downlink
except ImportError:
    from connectivity_common import authenticate, classify_target, queue_downlink


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

    def _auth_result(self) -> dict[str, Any]:
        return self.shared_auth_result or authenticate(
            self.base_url,
            self.account,
            self.password,
            self.auth_timeout,
        )

    def build_result(self, auth_result: dict[str, Any], queue_result: dict[str, Any], reference: str) -> dict[str, Any]:
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

    def run(self) -> dict[str, Any]:
        auth_result = self._auth_result()
        if not auth_result["ok"]:
            return {
                "result": "FAIL",
                "stage": "client_server",
                "target": classify_target(self.base_url),
                "base_url": self.base_url,
                "device_id": self.device_id,
                "auth": auth_result,
            }

        queue_result = queue_downlink(
            self.base_url,
            self.device_id,
            auth_result["token"],
            self.data_hex,
            self.fport,
            self.reference,
            self.queue_timeout,
        )
        return self.build_result(auth_result, queue_result, self.reference)
