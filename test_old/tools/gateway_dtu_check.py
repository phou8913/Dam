"""Gateway -> DTU connectivity check."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

from tools.common_check import (
    build_reference,
    classify_target,
    result_payload,
)


# Build the MQTT topic used to receive the device ACK.
def build_ack_topic(application_id: str, device_id: str) -> str:
    return f"application/{application_id}/device/{device_id}/ack"


# Fake mode reads ACKs from the local HTTP test server instead of MQTT.
def get_fake_ack(
    base_url: str,
    device_id: str,
    timeout: float = 5.0,
) -> dict[str, Any]:
    import requests

    url = f"{base_url}/v1/devices/{device_id}/ack"
    started = time.time()
    try:
        response = requests.get(url, timeout=timeout)
        elapsed_ms = round((time.time() - started) * 1000, 2)
    except requests.RequestException as exc:
        return result_payload(
            False,
            "ack",
            error_type="NETWORK_FAIL",
            error_message=str(exc),
            url=url,
        )

    try:
        body = response.json()
    except ValueError:
        body = None

    if not response.ok:
        return result_payload(
            False,
            "ack",
            error_type="HTTP_FAIL",
            error_message="Failed to fetch fake ack",
            url=url,
            status_code=response.status_code,
            elapsed_ms=elapsed_ms,
            response_body=body if body is not None else response.text,
        )

    return result_payload(
        True,
        "ack",
        url=url,
        status_code=response.status_code,
        elapsed_ms=elapsed_ms,
        payload=body if isinstance(body, dict) else {},
        acknowledged=body.get("acknowledged") if isinstance(body, dict) else None,
    )


# Small helper that connects, subscribes, and waits for one MQTT topic message.
class MqttTopicListener:
    # Store connection settings and mutable listener state.
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        client_id: str,
        keepalive: int,
        use_tls: bool,
        topic: str,
        expected_device_id: Optional[str] = None,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.client_id = client_id
        self.keepalive = keepalive
        self.use_tls = use_tls
        self.topic = topic
        self.expected_device_id = expected_device_id
        self.client: Optional["mqtt.Client"] = None
        self.connect_event = threading.Event()
        self.message_event = threading.Event()
        self.error: Optional[str] = None
        self.received_payload: Optional[dict[str, Any]] = None
        self.received_topic: Optional[str] = None
        self.received_at: Optional[float] = None

    # MQTT callbacks update the listener state as the client runs.
    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            client.subscribe(self.topic, qos=0)
            self.connect_event.set()
        else:
            self.error = f"MQTT connect failed with code {reason_code}"
            self.connect_event.set()

    def on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception as exc:
            self.error = f"Failed to parse topic payload: {exc}"
            self.message_event.set()
            return

        if self.expected_device_id is not None and str(payload.get("devEUI")) != self.expected_device_id:
            return

        self.received_payload = payload
        self.received_topic = msg.topic
        self.received_at = time.time()
        self.message_event.set()

    def on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties=None):
        if reason_code != 0 and not self.message_event.is_set():
            self.error = f"MQTT disconnected unexpectedly with code {reason_code}"
            self.message_event.set()

    # Open the MQTT connection and wait until subscription is ready.
    def start(self, timeout_sec: float) -> dict[str, Any]:
        if mqtt is None:
            return result_payload(
                False,
                "mqtt",
                error_type="DEPENDENCY_MISSING",
                error_message="Missing dependency: paho-mqtt. Install with 'pip install paho-mqtt'.",
            )

        try:
            self.client = mqtt.Client(client_id=self.client_id, protocol=mqtt.MQTTv311)
            self.client.username_pw_set(self.username, self.password)
            if self.use_tls:
                self.client.tls_set()
            self.client.on_connect = self.on_connect
            self.client.on_message = self.on_message
            self.client.on_disconnect = self.on_disconnect
            self.client.connect(self.host, self.port, self.keepalive)
            self.client.loop_start()
        except Exception as exc:
            return result_payload(
                False,
                "mqtt",
                error_type="NETWORK_FAIL",
                error_message=str(exc),
                host=self.host,
                port=self.port,
                topic=self.topic,
            )

        connected = self.connect_event.wait(timeout_sec)
        if not connected:
            self.stop()
            return result_payload(
                False,
                "mqtt",
                error_type="TIMEOUT",
                error_message="Timed out waiting for MQTT connection/subscription",
                host=self.host,
                port=self.port,
                topic=self.topic,
            )

        if self.error:
            self.stop()
            return result_payload(
                False,
                "mqtt",
                error_type="CONNECT_FAIL",
                error_message=self.error,
                host=self.host,
                port=self.port,
                topic=self.topic,
            )

        return result_payload(
            True,
            "mqtt",
            host=self.host,
            port=self.port,
            topic=self.topic,
            client_id=self.client_id,
        )

    # Wait for the expected topic message after the listener has started.
    def wait_for_message(
        self,
        timeout_sec: float,
        stage: str = "message",
        extra: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        got_message = self.message_event.wait(timeout_sec)
        if self.error and not self.received_payload:
            return result_payload(
                False,
                stage,
                error_type="MQTT_RUNTIME_FAIL",
                error_message=self.error,
                topic=self.topic,
                **(extra or {}),
            )

        if not got_message:
            return result_payload(
                False,
                stage,
                error_type="TIMEOUT",
                error_message="Timed out waiting for MQTT topic message",
                topic=self.topic,
                timeout_sec=timeout_sec,
                **(extra or {}),
            )

        return result_payload(
            True,
            stage,
            topic=self.received_topic,
            received_at=self.received_at,
            payload=self.received_payload,
            **(extra or {}),
        )

    # Stop the MQTT loop and close the connection.
    def stop(self):
        if self.client is not None:
            try:
                self.client.loop_stop()
                self.client.disconnect()
            except Exception:
                pass


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

    def prepare_ack_monitor(self, auth_result: dict[str, Any], reference: str | None = None) -> dict[str, Any]:
        # Set up ACK monitoring before the shared downlink is sent.
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
        # Use the queue result and ACK outcome to finish this segment.
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
                queue_ts = queue_result.get("timestamp")
                received_at = ack_result.get("received_at")
                if isinstance(queue_ts, (int, float)) and isinstance(received_at, (int, float)):
                    ack_result["elapsed_ms"] = round((received_at - queue_ts) * 1000, 2)
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

    @staticmethod
    def summarize(payload: dict[str, Any]) -> dict[str, Any]:
        # Keep only the fields that matter in the final end-to-end summary.
        if payload.get("result") == "NOT_RUN":
            return payload
        ack = payload.get("ack") or {}
        queue = payload.get("queue") or {}
        mqtt = payload.get("mqtt") or {}
        request_payload = queue.get("request_payload") or {}
        ack_payload = ack.get("payload") or {}
        failure_phase = None
        if payload.get("result") == "FAIL":
            if mqtt and not mqtt.get("ok", True):
                failure_phase = "mqtt_prepare"
            elif queue and not queue.get("ok", True):
                failure_phase = "queue"
            elif ack and not ack.get("ok", True):
                failure_phase = "ack"
        return {
            "result": payload.get("result"),
            "failure_phase": failure_phase,
            "mqtt_ok": mqtt.get("ok"),
            "queue_ok": queue.get("ok"),
            "ack_ok": ack.get("ok"),
            "acknowledged": ack.get("acknowledged"),
            "reference": payload.get("reference") or request_payload.get("reference") or ack_payload.get("reference"),
            "ack_topic": payload.get("ack_topic") or mqtt.get("topic"),
        }
