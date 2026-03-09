"""
LoRa API communicator with per-device request queues and latest-result buffer.
"""

import os
import time
import threading
import queue
import base64
from datetime import datetime
from typing import Optional, Tuple, Any, Dict, Callable, List

import requests

from humidity_temp_sensor import HumidityTempSensor
from tilt_acc_sensor import HWT901BSensor
from water_level_sensor import WaterLevelSensor
from mmwave_sensor import MMWaveSensor


# Backend mode and connection settings.
USE_FAKE_SERVER = os.getenv("USE_FAKE_SERVER") == "1"

REAL_BASE_URL = "http://99.10.226.29:4560/api"
FAKE_BASE_URL = "http://localhost:5000/api"


def _default_base_url(use_fake_server: bool) -> str:
    return FAKE_BASE_URL if use_fake_server else REAL_BASE_URL


# Switch the HTTP target depending on whether local simulation is enabled.
DEFAULT_BASE_URL = _default_base_url(USE_FAKE_SERVER)
BASE_URL = os.getenv("BASE_URL", DEFAULT_BASE_URL)
ACCOUNT = os.getenv("LORA_ACCOUNT", "admin")
PASSWORD = os.getenv("LORA_PASSWORD", "admin")


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
def _result(ok: bool, data: Any = None, error: Optional[str] = None) -> Dict[str, Any]:
    return {
        "ok": ok,
        "data": data,
        "error": error,
        "timestamp": time.time(),
    }


def _error_result(error: str) -> Dict[str, Any]:
    return _result(False, data=None, error=error)


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
                _write_buffer_result(self.dev_eui, sensor, _error_result(f"Worker exception: {e}"))


# Sensor-specific request handling and decoding.
def _handle_request(task: Dict[str, Any]):
    # Dispatch the sensor code to the matching reader and cache the latest result.
    dev_eui = str(task.get("dev_eui", "")).strip()
    sensor = str(task.get("sensor", "")).strip()
    if not dev_eui or not sensor:
        return

    dispatch_map: Dict[str, Callable[[str], Dict[str, Any]]] = {
        "ht": read_ht,
        "ta": read_ta,
        "wl": read_wl,
        "mmwave": read_mmwave,
    }

    reader = dispatch_map.get(sensor)
    if reader is None:
        result = _error_result(f"Unsupported sensor: {sensor}")
    else:
        result = reader(dev_eui)

    _write_buffer_result(dev_eui, sensor, result)


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


def send_request(
    device_id: str,
    data_to_send: str,
    auth_token: str,
    fport: int = 1,
    reference: str = "downlink-cmd",
    min_interval_sec: float = 1.0,
    timeout: float = 30.0,
) -> Tuple[int, Optional[Any]]:
    del timeout
    # Enforce minimum spacing so repeated downlinks do not pile up too quickly.
    send_lock = _get_send_lock(device_id)
    with send_lock:
        last_send_ts = _LAST_SEND_TS.get(device_id, 0.0)
        elapsed = time.time() - last_send_ts
        if elapsed < min_interval_sec:
            time.sleep(min_interval_sec - elapsed)
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
            response = requests.post(url, json=payload, headers=headers)
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
    response_validator: Callable[[str], bool],
    timeout_sec: float = 30.0,
    fport: int = 1,
    reference: str = "downlink-cmd",
    min_interval_sec: float = 1.0,
    poll_interval_sec: float = 1.0,
) -> Tuple[int, Optional[str]]:
    # For request/response sensors, send a command and wait for the next matching uplink.
    lock = _get_inflight_lock(device_id)
    with lock:
        send_time = time.time()
        status, _ = send_request(
            device_id,
            data_to_send,
            auth_token,
            fport,
            reference,
            min_interval_sec=min_interval_sec,
            timeout=timeout_sec,
        )
        if status != 1:
            print(f"[send_and_wait] Failed to send request to {device_id}")
            return 0, None

        deadline = send_time + timeout_sec
        while time.time() < deadline:
            time.sleep(poll_interval_sec)
            status, uplinks = pull_latest_uplinks(device_id, auth_token, size=20)
            if status != 1 or uplinks is None:
                continue

            for uplink in uplinks:
                with _RESPONSE_TS_LOCK:
                    last_resp_ts = _LAST_RESPONSE_TS.get(device_id, 0.0)

                if uplink["ts"] <= last_resp_ts or uplink["ts"] < send_time:
                    continue

                hex_data = uplink["hex"]
                try:
                    if response_validator(hex_data):
                        with _RESPONSE_TS_LOCK:
                            if uplink["ts"] <= _LAST_RESPONSE_TS.get(device_id, 0.0):
                                continue
                            _LAST_RESPONSE_TS[device_id] = uplink["ts"]
                        return 1, hex_data
                except Exception as e:
                    print(f"[send_and_wait] Validator error: {e}")

        print(f"[send_and_wait] Timeout waiting for response from {device_id}")
        return 0, None


def read_ht(dev_eui: str) -> Dict[str, Any]:
    # Request and decode one humidity/temperature sample.
    profile = HumidityTempSensor()
    try:
        token = get_token()
        status, hex_data = send_and_wait(
            device_id=dev_eui,
            data_to_send=profile.encode_read_command(),
            auth_token=token,
            response_validator=profile.validate_response,
            timeout_sec=15.0,
            fport=1,
            reference="humidity-read",
            min_interval_sec=1.0,
            poll_interval_sec=1.0,
        )
        if status != 1 or not hex_data:
            return _error_result("Failed to get response or timeout")
        decoded = profile.decode_response(hex_data)
        if not decoded:
            return _error_result("Failed to decode response")
        return _result(True, data=decoded)
    except Exception as e:
        return _error_result(str(e))


def read_ta(dev_eui: str) -> Dict[str, Any]:
    # IMU reads use an unlock step, then separate angle and acceleration requests.
    profile = HWT901BSensor()
    try:
        token = get_token()
        unlock_cmd = profile.encode_unlock_command()
        status, _ = send_request(
            device_id=dev_eui,
            data_to_send=unlock_cmd,
            auth_token=token,
            min_interval_sec=1.0,
        )
        if status != 1:
            return _error_result("Failed to send unlock command")

        time.sleep(0.5)

        status, angles_hex = send_and_wait(
            device_id=dev_eui,
            data_to_send=profile.encode_read_angles_command(),
            auth_token=token,
            response_validator=profile.validate_angles_response,
            timeout_sec=15.0,
            fport=1,
            reference="angles-read",
            min_interval_sec=1.0,
            poll_interval_sec=1.0,
        )
        if status != 1 or not angles_hex:
            return _error_result("Failed to read angles")

        status, accel_hex = send_and_wait(
            device_id=dev_eui,
            data_to_send=profile.encode_read_accel_command(),
            auth_token=token,
            response_validator=profile.validate_accel_response,
            timeout_sec=15.0,
            fport=1,
            reference="accel-read",
            min_interval_sec=1.0,
            poll_interval_sec=1.0,
        )
        if status != 1 or not accel_hex:
            return _error_result("Failed to read acceleration")

        angles_data = profile.decode_angles(angles_hex)
        accel_data = profile.decode_acceleration(accel_hex)
        if not angles_data:
            return _error_result("Failed to decode angles")
        if not accel_data:
            return _error_result("Failed to decode acceleration")

        combined = {}
        combined.update(angles_data)
        combined.update(accel_data)
        return _result(True, data=combined)
    except Exception as e:
        return _error_result(str(e))


def read_wl(dev_eui: str) -> Dict[str, Any]:
    # Request and decode one water level sample.
    profile = WaterLevelSensor()
    try:
        token = get_token()
        status, hex_data = send_and_wait(
            device_id=dev_eui,
            data_to_send=profile.encode_read_command(),
            auth_token=token,
            response_validator=profile.validate_response,
            timeout_sec=15.0,
            fport=1,
            reference="water-level-read",
            min_interval_sec=1.0,
            poll_interval_sec=1.0,
        )
        if status != 1 or not hex_data:
            return _error_result("Failed to get response or timeout")
        decoded = profile.decode_response(hex_data)
        if not decoded:
            return _error_result("Failed to decode response")
        return _result(True, data=decoded)
    except Exception as e:
        return _error_result(str(e))


def read_mmwave(dev_eui: str) -> Dict[str, Any]:
    # Radar data is uplink-only here, so just pull and decode the latest packet.
    profile = MMWaveSensor()
    try:
        token = get_token()
        status, uplinks = pull_latest_uplinks(
            device_id=dev_eui,
            auth_token=token,
            size=10,
        )
        if status != 1 or not uplinks:
            return _error_result("Failed to pull latest uplink")
        hex_data = uplinks[0]["hex"]
        targets = profile.decode_targets(hex_data)
        if not targets:
            return _error_result("No targets detected or failed to decode")
        return _result(True, data={"targets": targets})
    except Exception as e:
        return _error_result(str(e))


# Start the background router as soon as this module is imported.
start_router()
