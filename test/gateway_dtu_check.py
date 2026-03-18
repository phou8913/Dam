"""Gateway -> DTU connectivity check."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from .connectivity_common import (
        MqttTopicListener,
        authenticate,
        build_ack_topic,
        build_reference,
        classify_target,
        get_fake_ack,
        queue_downlink,
    )
except ImportError:
    from connectivity_common import (
        MqttTopicListener,
        authenticate,
        build_ack_topic,
        build_reference,
        classify_target,
        get_fake_ack,
        queue_downlink,
    )


@dataclass
class GatewayDtuCheck:
    base_url: str
    account: str
    password: str
    device_id: str
    application_id: str
    data_hex: str = "01"
    fport: int = 1
    reference: str = ""
    auth_timeout: float = 5.0
    queue_timeout: float = 10.0
    ack_timeout: float = 20.0
    mqtt_host: str = "99.10.226.29"
    mqtt_port: int = 1883
    mqtt_username: str = "mqtt_user_1"
    mqtt_password: str = "mqtt_pass_1"
    mqtt_client_id: str = "mqtt_client_1"
    mqtt_keepalive: int = 60
    mqtt_tls: bool = False
    shared_auth_result: dict[str, Any] | None = None

    def _auth_result(self) -> dict[str, Any]:
        return self.shared_auth_result or authenticate(
            self.base_url,
            self.account,
            self.password,
            self.auth_timeout,
        )

    def prepare_ack_monitor(self, auth_result: dict[str, Any] | None = None, reference: str | None = None) -> dict[str, Any]:
        auth_result = auth_result or self._auth_result()
        reference = reference or self.reference or build_reference("gw-dtu-test")
        ack_topic = build_ack_topic(self.application_id, self.device_id)
        target = classify_target(self.base_url)
        listener = None

        if not auth_result["ok"]:
            return {
                "ok": False,
                "auth_result": auth_result,
                "reference": reference,
                "ack_topic": ack_topic,
            }

        if target == "fake":
            mqtt_result = {
                "ok": True,
                "stage": "mqtt",
                "timestamp": None,
                "host": "fake-server",
                "port": None,
                "topic": ack_topic,
                "client_id": None,
                "mode": "fake-http-ack",
            }
        else:
            listener = MqttTopicListener(
                host=self.mqtt_host,
                port=self.mqtt_port,
                username=self.mqtt_username,
                password=self.mqtt_password,
                client_id=self.mqtt_client_id,
                keepalive=self.mqtt_keepalive,
                use_tls=self.mqtt_tls,
                topic=ack_topic,
                expected_device_id=self.device_id,
            )
            mqtt_result = listener.start(timeout_sec=5.0)

        return {
            "ok": mqtt_result.get("ok", False),
            "auth_result": auth_result,
            "reference": reference,
            "ack_topic": ack_topic,
            "target": target,
            "listener": listener,
            "mqtt_result": mqtt_result,
        }

    def finalize_with_queue(self, prepared: dict[str, Any], queue_result: dict[str, Any]) -> dict[str, Any]:
        auth_result = prepared["auth_result"]
        mqtt_result = prepared["mqtt_result"]
        listener = prepared.get("listener")
        target = prepared.get("target")
        reference = prepared["reference"]
        ack_topic = prepared["ack_topic"]

        if not queue_result["ok"]:
            if listener is not None:
                listener.stop()
            return {
                "result": "FAIL",
                "stage": "gateway_dtu",
                "base_url": self.base_url,
                "application_id": self.application_id,
                "device_id": self.device_id,
                "auth": {
                    "ok": True,
                    "status_code": auth_result.get("status_code"),
                    "elapsed_ms": auth_result.get("elapsed_ms"),
                },
                "mqtt": mqtt_result,
                "queue": queue_result,
            }

        if target == "fake":
            ack_result = get_fake_ack(self.base_url, self.device_id, timeout=self.ack_timeout)
        else:
            ack_result = listener.wait_for_message(self.ack_timeout, stage="ack")
            if ack_result.get("ok"):
                payload = ack_result.get("payload") or {}
                ack_result["acknowledged"] = payload.get("acknowledged")
            listener.stop()

        success = ack_result["ok"] and ack_result.get("acknowledged") is True
        return {
            "result": "PASS" if success else "FAIL",
            "stage": "gateway_dtu",
            "base_url": self.base_url,
            "application_id": self.application_id,
            "device_id": self.device_id,
            "ack_topic": ack_topic,
            "reference": reference,
            "auth": {
                "ok": True,
                "status_code": auth_result.get("status_code"),
                "elapsed_ms": auth_result.get("elapsed_ms"),
            },
            "mqtt": mqtt_result,
            "queue": queue_result,
            "ack": ack_result,
        }

    def run(self) -> dict[str, Any]:
        auth_result = self._auth_result()
        if not auth_result["ok"]:
            return {
                "result": "FAIL",
                "stage": "gateway_dtu",
                "base_url": self.base_url,
                "application_id": self.application_id,
                "device_id": self.device_id,
                "auth": auth_result,
            }

        prepared = self.prepare_ack_monitor(auth_result=auth_result)
        if not prepared["ok"]:
            return {
                "result": "FAIL",
                "stage": "gateway_dtu",
                "base_url": self.base_url,
                "application_id": self.application_id,
                "device_id": self.device_id,
                "auth": {
                    "ok": True,
                    "status_code": auth_result.get("status_code"),
                    "elapsed_ms": auth_result.get("elapsed_ms"),
                },
                "mqtt": prepared.get("mqtt_result"),
            }

        queue_result = queue_downlink(
            self.base_url,
            self.device_id,
            auth_result["token"],
            self.data_hex,
            self.fport,
            prepared["reference"],
            self.queue_timeout,
        )
        return self.finalize_with_queue(prepared, queue_result)
