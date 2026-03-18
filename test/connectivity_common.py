"""
Shared helpers for connectivity test scripts.
"""

import base64
import json
import os
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

import requests


REAL_BASE_URL = "http://99.10.226.29:4560/api"
FAKE_BASE_URL = "http://localhost:5000/api"


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


def result_payload(ok: bool, stage: str, **extra: Any) -> Dict[str, Any]:
    payload = {
        "ok": ok,
        "stage": stage,
        "timestamp": time.time(),
    }
    payload.update(extra)
    return payload


def build_reference(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def build_ack_topic(application_id: str, device_id: str) -> str:
    return f"application/{application_id}/device/{device_id}/ack"


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


def pull_latest_uplinks(
    base_url: str,
    device_id: str,
    token: str,
    size: int = 10,
    timeout: float = 10.0,
) -> Dict[str, Any]:
    url = f"{base_url}/v1/uplink-storage/devices/{device_id}/uplink"
    headers = {"token": token}
    params = {"size": size, "page": 1}

    started = time.time()
    try:
        response = requests.get(url, headers=headers, params=params, timeout=timeout)
        elapsed_ms = round((time.time() - started) * 1000, 2)
    except requests.RequestException as exc:
        return result_payload(
            False,
            "uplink",
            error_type="NETWORK_FAIL",
            error_message=str(exc),
            url=url,
            params=params,
        )

    try:
        body = response.json()
    except ValueError:
        body = None

    if not response.ok:
        return result_payload(
            False,
            "uplink",
            error_type="HTTP_FAIL",
            error_message="Failed to query uplinks",
            url=url,
            status_code=response.status_code,
            elapsed_ms=elapsed_ms,
            params=params,
            response_body=body if body is not None else response.text,
        )

    uplinks_raw = body.get("result", []) if isinstance(body, dict) else []
    parsed_uplinks: List[Dict[str, Any]] = []

    for uplink in uplinks_raw:
        raw_b64 = uplink.get("data")
        fport = uplink.get("fPort", 0)
        ts_str = uplink.get("insertTime")
        ts = _parse_insert_time(ts_str)
        decoded_hex = None

        if raw_b64:
            try:
                decoded_hex = base64.b64decode(raw_b64).hex()
            except Exception:
                decoded_hex = None

        parsed_uplinks.append({
            "ts": ts,
            "fport": fport,
            "hex": decoded_hex,
            "raw": uplink,
        })

    return result_payload(
        True,
        "uplink",
        url=url,
        status_code=response.status_code,
        elapsed_ms=elapsed_ms,
        params=params,
        uplinks=parsed_uplinks,
    )


def get_fake_ack(
    base_url: str,
    device_id: str,
    timeout: float = 5.0,
) -> Dict[str, Any]:
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


def _parse_insert_time(ts_str: Optional[str]) -> float:
    if not ts_str:
        return time.time()

    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
    except Exception:
        return time.time()


class MqttTopicListener:
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
        self.received_payload: Optional[Dict[str, Any]] = None
        self.received_topic: Optional[str] = None
        self.received_at: Optional[float] = None

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

    def start(self, timeout_sec: float) -> Dict[str, Any]:
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

    def wait_for_message(self, timeout_sec: float, stage: str = "message", extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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

    def stop(self):
        if self.client is not None:
            try:
                self.client.loop_stop()
                self.client.disconnect()
            except Exception:
                pass
