"""
LoRa API communicator with per-device request queues and latest-result buffer.
"""

import os
import time
import threading
import queue
import base64
from datetime import datetime
from typing import Optional, Tuple, Any, Dict, List

import requests
try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None
try:
    from colorama import Fore, Style, init as colorama_init
    colorama_init()
except ImportError:
    Fore = Style = None

from profiles.humidity_temp_sensor import HumidityTempSensor
from profiles.tilt_acc_sensor import HWT901BSensor
from profiles.water_level_sensor import WaterLevelSensor
from profiles.mmwave_sensor import MMWaveSensor


# Backend mode and connection settings.
USE_FAKE_SERVER = os.getenv("USE_FAKE_SERVER") == "1"

REAL_BASE_URL = "http://99.10.226.29:4560/api"
FAKE_BASE_URL = "http://127.0.0.1:5000/api"
APPLICATION_ID = os.getenv("APPLICATION_ID", "18")

MQTT_HOST = os.getenv("MQTT_HOST", "99.10.226.29")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "mqtt_user_1")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "mqtt_pass_1")
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "mqtt_client_1")
MQTT_KEEPALIVE = int(os.getenv("MQTT_KEEPALIVE", "60"))


def _default_base_url(use_fake_server: bool) -> str:
    return FAKE_BASE_URL if use_fake_server else REAL_BASE_URL


# Switch the HTTP target depending on whether local simulation is enabled.
DEFAULT_BASE_URL = _default_base_url(USE_FAKE_SERVER)
BASE_URL = os.getenv("BASE_URL", DEFAULT_BASE_URL)
ACCOUNT = os.getenv("LORA_ACCOUNT", "admin")
PASSWORD = os.getenv("LORA_PASSWORD", "admin")


# Terminal logging helpers for queued requests and sensor results.
_SENSOR_LABELS = {
    "ht": "Humidity/Temperature Sensor",
    "ta": "Tilt/Acceleration Sensor",
    "wl": "Water Level Sensor",
    "mmwave": "mmWave Radar Sensor",
}


def _log_line(message: str = ""):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {message}")


def _red_text(message: str) -> str:
    if Fore and Style:
        return f"{Fore.RED}{message}{Style.RESET_ALL}"
    return message


def _log_sensor_header(sensor: str):
    _log_line()
    print(f"--- {_SENSOR_LABELS.get(sensor, sensor)} ---")


def _log_sensor_result(sensor: str, result: Dict[str, Any]):
    data = result.get("data") or {}
    if not result.get("ok"):
        stage = result.get("error_stage") or "unknown"
        reason = result.get("error") or "Unknown error"
        _log_line(_red_text(f"Error at {stage}: {reason}"))
        return

    if sensor == "ht":
        _log_line(f"Temperature: {data.get('temperature_c', 0.0):.2f} °C")
        _log_line(f"Humidity: {data.get('humidity_rh', 0.0):.2f} %RH")
        _log_line(f"Dewpoint: {data.get('dewpoint_c', 0.0):.2f} °C")
        _log_line(f"CRC Valid: {data.get('crc_valid', '--')}")
        _log_line(f"Raw: {data.get('raw_hex', '--')}")
    elif sensor == "ta":
        _log_line(f"Roll: {data.get('roll', 0.0):.2f}°")
        _log_line(f"Pitch: {data.get('pitch', 0.0):.2f}°")
        _log_line(f"Yaw: {data.get('yaw', 0.0):.2f}°")
        _log_line(f"Ax: {data.get('ax_g', 0.0):.3f}g ({data.get('ax_ms2', 0.0):.2f} m/s²)")
        _log_line(f"Ay: {data.get('ay_g', 0.0):.3f}g ({data.get('ay_ms2', 0.0):.2f} m/s²)")
        _log_line(f"Az: {data.get('az_g', 0.0):.3f}g ({data.get('az_ms2', 0.0):.2f} m/s²)")
        _log_line(f"Raw: {data.get('raw_hex', '--')}")
    elif sensor == "wl":
        _log_line(f"Water Level: {data.get('level_m', 0.0):.3f} m")
        _log_line(f"CRC Valid: {data.get('crc_valid', '--')}")
        _log_line(f"Raw: {data.get('raw_hex', '--')}")
    elif sensor == "mmwave":
        targets = data.get("targets", {}) if isinstance(data, dict) else {}
        _log_line(f"Detected {len(targets)} targets:")
        for target_name, target_data in targets.items():
            if len(target_data) >= 2:
                angle, distance = target_data[0], target_data[1]
                _log_line(f"  {target_name}: {angle:.1f}° @ {distance:.2f}m")
    else:
        _log_line(f"Result: {data}")

    updated_at = datetime.now().strftime("%H:%M:%S")
    _log_line(f"Updated at: {updated_at}")


# Shared queues and buffers used across threads.
request_queue = queue.Queue()

buffer: Dict[str, Dict[str, Dict[str, Any]]] = {}
buffer_lock = threading.Lock()

# Per-device locks and worker registries.
_LAST_SEND_TS: Dict[str, float] = {}
_SEND_LOCKS: Dict[str, threading.Lock] = {}
_SEND_LOCKS_GUARD = threading.Lock()

_LAST_RESPONSE_TS: Dict[str, float] = {}
_RESPONSE_TS_LOCK = threading.Lock()

_INFLIGHT_LOCKS: Dict[str, threading.Lock] = {}
_INFLIGHT_LOCKS_GUARD = threading.Lock()

_DEVICE_WORKERS: Dict[str, "_DeviceWorker"] = {}
_DEVICE_WORKERS_LOCK = threading.Lock()


# Standard result wrappers for sensor reads.
def _result(
    ok: bool,
    data: Any = None,
    error: Optional[str] = None,
    error_stage: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "ok": ok,
        "data": data,
        "error": error,
        "error_stage": error_stage,
        "timestamp": time.time(),
    }


def _error_result(error: str, error_stage: str) -> Dict[str, Any]:
    return _result(False, data=None, error=error, error_stage=error_stage)


# Backend selection and shared buffer helpers.
### gui.py uses this to switch between real and fake server
def configure_backend(mode: str = "real"):
    """Switch communicator traffic between the real gateway and the fake local server."""
    global USE_FAKE_SERVER, DEFAULT_BASE_URL, BASE_URL
    use_fake_server = mode == "fake"
    USE_FAKE_SERVER = use_fake_server
    DEFAULT_BASE_URL = _default_base_url(use_fake_server)

    if use_fake_server:
        os.environ["USE_FAKE_SERVER"] = "1"
    else:
        os.environ.pop("USE_FAKE_SERVER", None)

    BASE_URL = os.getenv("BASE_URL", DEFAULT_BASE_URL)

### gui.py uses this to get the latest result for a given device and sensor.
def get_buffer_data(dev_eui: str, sensor: str) -> Optional[Dict[str, Any]]:
    with buffer_lock:
        return buffer.get(dev_eui, {}).get(sensor)


def _write_buffer_result(dev_eui: str, sensor: str, result: Dict[str, Any]):
    with buffer_lock:
        if dev_eui not in buffer:
            buffer[dev_eui] = {}
        buffer[dev_eui][sensor] = result

### gui.py uses this to request a new reading for a given device and sensor.
def enqueue_request(dev_eui: str, sensor: str):
    # The GUI only queues work; device workers do the blocking I/O.
    _log_sensor_header(sensor)
    _log_line("Read request queued, waiting for response...")
    request_queue.put({
        "dev_eui": str(dev_eui).strip(),
        "sensor": str(sensor).strip(),
        "timestamp": time.time(),
    })


# Per-device locking and worker lifecycle.
def _get_send_lock(dev_eui: str) -> threading.Lock:
    with _SEND_LOCKS_GUARD:
        lock = _SEND_LOCKS.get(dev_eui)
        if lock is None:
            lock = threading.Lock()
            _SEND_LOCKS[dev_eui] = lock
        return lock


def _get_inflight_lock(dev_eui: str) -> threading.Lock:
    with _INFLIGHT_LOCKS_GUARD:
        lock = _INFLIGHT_LOCKS.get(dev_eui)
        if lock is None:
            lock = threading.Lock()
            _INFLIGHT_LOCKS[dev_eui] = lock
        return lock


class _DeviceWorker:
    """Serial worker for a single device EUI."""

    def __init__(self, dev_eui: str):
        self.dev_eui = dev_eui
        self.queue: queue.Queue = queue.Queue()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def enqueue(self, task: Dict[str, Any]):
        self.queue.put(task)

    def _run(self):
        while True:
            task = self.queue.get()
            try:
                _handle_request(task)
            except Exception as e:
                sensor = task.get("sensor", "")
                _write_buffer_result(self.dev_eui, sensor, _error_result(f"Worker exception: {e}", "client->server"))


# Sensor-specific request handling and decoding.
def _handle_request(task: Dict[str, Any]):
    # Dispatch the sensor code to the matching reader and cache the latest result.
    dev_eui = str(task.get("dev_eui", "")).strip()
    sensor = str(task.get("sensor", "")).strip()
    if not dev_eui or not sensor:
        return

    dispatch_map = {
        "ht": read_ht,
        "ta": read_ta,
        "wl": read_wl,
        "mmwave": read_mmwave,
    }

    reader = dispatch_map.get(sensor)
    if reader is None:
        result = _error_result(f"Unsupported sensor: {sensor}", "client->server")
    else:
        result = reader(dev_eui)

    _write_buffer_result(dev_eui, sensor, result)
    print(f"[_DeviceWorker:{dev_eui}] Updated buffer {sensor} ok={result.get('ok', False)}")
    _log_sensor_result(sensor, result)


def _get_device_worker(dev_eui: str) -> _DeviceWorker:
    with _DEVICE_WORKERS_LOCK:
        worker = _DEVICE_WORKERS.get(dev_eui)
        if worker is None:
            worker = _DeviceWorker(dev_eui)
            _DEVICE_WORKERS[dev_eui] = worker
        return worker


# Request routing from the global queue to device workers.
def _dispatch_request(task: Dict[str, Any]):
    # Route each task to the worker dedicated to that device.
    dev_eui = str(task.get("dev_eui", "")).strip()
    sensor = str(task.get("sensor", "")).strip()
    if not dev_eui or not sensor:
        return
    worker = _get_device_worker(dev_eui)
    worker.enqueue(task)


def _request_router_loop():
    # Global router fan-outs queued requests into per-device workers.
    while True:
        task = request_queue.get()
        _dispatch_request(task)


def start_router():
    thread = threading.Thread(target=_request_router_loop, daemon=True)
    thread.start()
    return thread


# HTTP communication helpers for the LoRa backend.
def get_token() -> str:
    url = f"{BASE_URL}/v1/internal/auth"
    payload = {
        "account": ACCOUNT,
        "password": PASSWORD,
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        token = response.json().get("token")
        if not token:
            raise RuntimeError("Authentication successful but no token received")
        return token
    except Exception as e:
        raise RuntimeError(f"Failed to authenticate: {e}")


def build_ack_topic(application_id: str, device_id: str) -> str:
    return f"application/{application_id}/device/{device_id}/ack"


class AckListener:
    """Wait for one ACK message from MQTT."""

    def __init__(self, topic: str):
        self.topic = topic
        self.client = None
        self.connect_event = threading.Event()
        self.message_event = threading.Event()
        self.payload: Optional[Dict[str, Any]] = None
        self.error: Optional[str] = None

    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            client.subscribe(self.topic, qos=0)
            self.connect_event.set()
        else:
            self.error = f"MQTT connect failed with code {reason_code}"
            self.connect_event.set()

    def on_message(self, client, userdata, msg):
        import json

        try:
            self.payload = json.loads(msg.payload.decode("utf-8"))
        except Exception as exc:
            self.error = f"Failed to parse ACK payload: {exc}"
        self.message_event.set()

    def start(self, timeout_sec: float) -> bool:
        if mqtt is None:
            self.error = "Missing dependency: paho-mqtt"
            return False

        try:
            self.client = mqtt.Client(client_id=MQTT_CLIENT_ID, protocol=mqtt.MQTTv311)
            if MQTT_USERNAME:
                self.client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
            self.client.on_connect = self.on_connect
            self.client.on_message = self.on_message
            self.client.connect(MQTT_HOST, MQTT_PORT, MQTT_KEEPALIVE)
            self.client.loop_start()
        except Exception as exc:
            self.error = str(exc)
            return False

        connected = self.connect_event.wait(timeout_sec)
        return connected and self.error is None

    def wait(self, timeout_sec: float) -> Tuple[int, Optional[Dict[str, Any]]]:
        got_message = self.message_event.wait(timeout_sec)
        if not got_message or self.error:
            return 0, None
        return 1, self.payload

    def stop(self):
        if self.client is not None:
            try:
                self.client.loop_stop()
                self.client.disconnect()
            except Exception:
                pass


def get_ack(device_id: str, timeout_sec: float = 10.0) -> Tuple[int, Optional[Dict[str, Any]]]:
    if USE_FAKE_SERVER:
        try:
            url = f"{BASE_URL}/v1/devices/{device_id}/ack"
            response = requests.get(url, timeout=timeout_sec)
            response.raise_for_status()
            return 1, response.json()
        except Exception as exc:
            print(f"Error getting ack: {exc}")
            return 0, None

    topic = build_ack_topic(APPLICATION_ID, device_id)
    listener = AckListener(topic)
    started = listener.start(timeout_sec)
    if not started:
        print(f"Error getting ack: {listener.error or 'Failed to start MQTT listener'}")
        listener.stop()
        return 0, None

    status, payload = listener.wait(timeout_sec)
    listener.stop()
    if status != 1 or payload is None:
        print(f"Error getting ack: {listener.error or 'Timed out waiting for ACK'}")
        return 0, None
    return 1, payload


def send_request(
    device_id: str,
    data_to_send: str,
    auth_token: str,
    fport: int = 1,
    reference: str = "downlink-cmd",
    request_interval_sec: float = 1.0, ### recommend for real environment: 1.0     Extreme: 0.0 for testing
    http_timeout_sec: float = 5.0, ### recommend for real environment: 5.0         Extreme: 1.0 for testing
) -> Tuple[int, Optional[Any]]:
    # Enforce minimum spacing so repeated downlinks do not pile up too quickly.
    send_lock = _get_send_lock(device_id)
    with send_lock:
        last_send_ts = _LAST_SEND_TS.get(device_id, 0.0)
        elapsed = time.time() - last_send_ts
        if elapsed < request_interval_sec:
            time.sleep(request_interval_sec - elapsed)
        _LAST_SEND_TS[device_id] = time.time()
        try:
            url = f"{BASE_URL}/v1/devices/{device_id}/queue"
            headers = {
                "token": auth_token,
                "content-type": "application/json",
            }
            payload = {
                "confirmed": True,
                "mode": "hex",
                "data": data_to_send,
                "fPort": fport,
                "reference": reference,
            }
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=http_timeout_sec,
            )
            response.raise_for_status()
            return 1, response.json()
        except Exception as e:
            print(f"Error sending request: {e}")
            return 0, None


def pull_latest_uplinks(
    device_id: str,
    auth_token: str,
    size: int = 10,
) -> Tuple[int, Optional[List[Dict[str, Any]]]]:
    try:
        url = f"{BASE_URL}/v1/uplink-storage/devices/{device_id}/uplink"
        headers = {"token": auth_token}
        params = {"size": size, "page": 1}
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()

        uplinks_raw = response.json().get("result", [])
        uplinks: List[Dict[str, Any]] = []

        for uplink in uplinks_raw:
            raw_b64 = uplink.get("data")
            fport = uplink.get("fPort", 0)
            ts_str = uplink.get("insertTime")
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
                except Exception as e:
                    print(f"Warning: Failed to parse insertTime '{ts_str}': {e}")
                    ts = time.time()
            else:
                ts = time.time()

            if raw_b64 and fport > 0:
                try:
                    raw_bytes = base64.b64decode(raw_b64)
                    uplinks.append({
                        "ts": ts,
                        "fport": fport,
                        "hex": raw_bytes.hex(),
                        "raw": uplink,
                    })
                except Exception as e:
                    print(f"Warning: Failed to decode uplink: {e}")

        if uplinks:
            return 1, uplinks
        return 0, None
    except Exception as e:
        print(f"Error pulling uplinks: {e}")
        return 0, None


def send_and_wait(
    device_id: str,
    data_to_send: str,
    auth_token: str,
    response_timeout_sec: float = 10.0, ### recommend for real environment: 10.0        Extreme: 1.0 for testing
    fport: int = 1,
    reference: str = "downlink-cmd",
    poll_interval_sec: float = 0.5, ### recommend for real environment: 0.5          Extreme: 0.01 for testing
) -> Tuple[int, Optional[str], Optional[str], Optional[str]]:
    # For request/response sensors, send a command and wait for the next matching uplink.
    freshness_slack_sec = 0.01
    lock = _get_inflight_lock(device_id)
    with lock:
        send_time = time.time()
        status, _ = send_request(
            device_id,
            data_to_send,
            auth_token,
            fport,
            reference,
        )
        if status != 1:
            print(f"[send_and_wait] Failed to send request to {device_id}")
            return 0, None, "client->server", "Failed to send request"

        ack_status, ack_payload = get_ack(device_id, timeout_sec=response_timeout_sec)
        if ack_status != 1 or ack_payload is None:
            return 0, None, "gateway->dtu", "No ACK received"

        if not ack_payload.get("acknowledged", False):
            warning_message = (
                f"Warning: ACK received for {device_id}, but acknowledged=false; continuing to wait for uplink."
            )
            if Fore and Style:
                warning_message = f"{Fore.YELLOW}{warning_message}{Style.RESET_ALL}"
            _log_line(warning_message)

        deadline = send_time + response_timeout_sec
        while time.time() < deadline:
            time.sleep(poll_interval_sec)
            status, uplinks = pull_latest_uplinks(device_id, auth_token, size=20)
            if status != 1 or uplinks is None:
                continue

            for uplink in uplinks:
                with _RESPONSE_TS_LOCK:
                    last_resp_ts = _LAST_RESPONSE_TS.get(device_id, 0.0)

                if uplink["ts"] <= last_resp_ts or uplink["ts"] < (send_time - freshness_slack_sec):
                    continue

                hex_data = uplink["hex"]
                with _RESPONSE_TS_LOCK:
                    if uplink["ts"] <= _LAST_RESPONSE_TS.get(device_id, 0.0):
                        continue
                    _LAST_RESPONSE_TS[device_id] = uplink["ts"]
                return 1, hex_data, None, None

        print(f"[send_and_wait] Timeout waiting for response from {device_id}")
        return 0, None, "dtu->sensor", "No uplink received after ACK"


# Run bundled sensor steps that must stay in sequence.
def _run_bundle(
    profile: Any,
    dev_eui: str,
    auth_token: str,
    steps: List[str],
) -> Tuple[bool, Dict[str, Any], Optional[str], Optional[str]]:
    results: Dict[str, Any] = {}

    for mode in steps:
        command_hex = profile.build_request(mode).hex()
        reference = mode
        result_key = mode
        wait_error = f"Failed to get response for {mode}"
        decode_error = f"Failed to decode response for {mode}"
        request_kwargs = {
            "device_id": dev_eui,
            "data_to_send": command_hex,
            "auth_token": auth_token,
            "fport": 1,
            "reference": reference,
        }

        status, hex_data, error_stage, error_reason = send_and_wait(**request_kwargs)
        if status != 1 or not hex_data:
            return False, results, error_stage or "gateway->dtu", error_reason or wait_error

        decoded = profile.decode_response(hex_data, mode=mode)
        if not decoded:
            return False, results, "dtu->sensor", decode_error

        if result_key:
            results[result_key] = decoded

    return True, results, None, None


def read_ht(dev_eui: str) -> Dict[str, Any]:
    # Request and decode one humidity/temperature sample.
    profile = HumidityTempSensor()
    try:
        token = get_token()
    except Exception as e:
        return _error_result(str(e), "client->server")
    try:
        steps = ["read"]
        ok, bundle_results, error_stage, error = _run_bundle(profile, dev_eui, token, steps)
        if not ok:
            return _error_result(error or "Bundle failed", error_stage or "client->server")
        return _result(True, data=bundle_results["read"])
    except Exception as e:
        return _error_result(str(e), "client->server")


def read_ta(dev_eui: str) -> Dict[str, Any]:
    # IMU reads bundle an unlock step with separate angle and acceleration reads.
    profile = HWT901BSensor()
    try:
        token = get_token()
    except Exception as e:
        return _error_result(str(e), "client->server")
    try:
        steps = ["unlock", "angles", "accel"]
        ok, bundle_results, error_stage, error = _run_bundle(profile, dev_eui, token, steps)
        if not ok:
            return _error_result(error or "Bundle failed", error_stage or "client->server")

        combined = {}
        combined.update(bundle_results["angles"])
        combined.update(bundle_results["accel"])
        return _result(True, data=combined)
    except Exception as e:
        return _error_result(str(e), "client->server")


def read_wl(dev_eui: str) -> Dict[str, Any]:
    # Request and decode one water level sample.
    profile = WaterLevelSensor()
    try:
        token = get_token()
    except Exception as e:
        return _error_result(str(e), "client->server")
    try:
        steps = ["read"]
        ok, bundle_results, error_stage, error = _run_bundle(profile, dev_eui, token, steps)
        if not ok:
            return _error_result(error or "Bundle failed", error_stage or "client->server")
        return _result(True, data=bundle_results["read"])
    except Exception as e:
        return _error_result(str(e), "client->server")


def read_mmwave(dev_eui: str) -> Dict[str, Any]:
    # Radar data is uplink-only here, so just pull and decode the latest packet.
    profile = MMWaveSensor()
    try:
        token = get_token()
    except Exception as e:
        return _error_result(str(e), "client->server")
    try:
        status, uplinks = pull_latest_uplinks(
            device_id=dev_eui,
            auth_token=token,
            size=10,
        )
        if status != 1 or not uplinks:
            return _error_result("Failed to pull latest uplink", "dtu->sensor")
        hex_data = uplinks[0]["hex"]
        targets = profile.decode_targets(hex_data)
        if not targets:
            return _error_result("No targets detected or failed to decode", "dtu->sensor")
        return _result(True, data={"targets": targets})
    except Exception as e:
        return _error_result(str(e), "client->server")


# Start the background router as soon as this module is imported.
start_router()
