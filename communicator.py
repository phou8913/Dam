"""
LoRa API Communicator with Per-DTU Rate Limiting
Unified interface for both fake and real LoRa gateway APIs.
- Per-DTU request queueing to enforce minimum send interval
- Request-response matching with timeout
"""

import os
import time
import threading
import queue
import base64
import struct
from datetime import datetime
from typing import Optional, Tuple, Any, Dict, Callable, List
from collections import defaultdict


# ==================== Import Configuration ====================
import requests

USE_FAKE_SERVER = os.getenv("USE_FAKE_SERVER") == "1"

if USE_FAKE_SERVER:
    DEFAULT_BASE_URL = "http://localhost:5000/api"
else:
    DEFAULT_BASE_URL = "http://99.10.226.29:4560/api"

class _Backend:
    """Unified LoRa API communicator (works with real or fake HTTP server)"""

    BASE_URL = os.getenv("BASE_URL", DEFAULT_BASE_URL)
    ACCOUNT = os.getenv("LORA_ACCOUNT", "admin")
    PASSWORD = os.getenv("LORA_PASSWORD", "admin")

    @staticmethod
    def get_token() -> str:
        """Authenticate with the API and retrieve JWT token."""
        url = f"{_Backend.BASE_URL}/v1/internal/auth"
        payload = {
            "account": _Backend.ACCOUNT,
            "password": _Backend.PASSWORD
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

    @staticmethod
    def send_request(
        device_id: str,
        data_to_send: str,
        auth_token: str,
        fport: int = 1,
        reference: str = "downlink-cmd"
    ) -> Tuple[int, Optional[Any]]:
        """Send downlink request to a LoRa device."""
        try:
            url = f"{_Backend.BASE_URL}/v1/devices/{device_id}/queue"
            headers = {
                "token": auth_token,
                "content-type": "application/json"
            }
            payload = {
                "confirmed": True,
                "mode": "hex",
                "data": data_to_send,
                "fPort": fport,
                "reference": reference
            }
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return (1, response.json())
        except Exception as e:
            print(f"Error sending request: {e}")
            return (0, None)

    @staticmethod
    def pull_latest_uplinks(
        device_id: str,
        auth_token: str,
        size: int = 10
    ) -> Tuple[int, Optional[List[Dict[str, Any]]]]:
        """
        Pull latest uplinks with timestamp and metadata.
        Returns list of dicts: {ts, fport, hex, ...}
        """
        try:
            url = f"{_Backend.BASE_URL}/v1/uplink-storage/devices/{device_id}/uplink"
            headers = {"token": auth_token}
            params = {"size": size, "page": 1}
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()

            uplinks_raw = response.json().get("result", [])
            uplinks = []

            for u in uplinks_raw:
                raw_b64 = u.get("data")
                fport = u.get("fPort", 0)
                ts_str = u.get("insertTime")
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
                        hex_data = raw_bytes.hex()
                        uplinks.append({
                            "ts": ts,
                            "fport": fport,
                            "hex": hex_data,
                            "raw": u
                        })
                    except Exception as e:
                        print(f"Warning: Failed to decode uplink: {e}")

            if uplinks:
                return (1, uplinks)
            return (0, None)

        except Exception as e:
            print(f"Error pulling uplinks: {e}")
            return (0, None)

_backend = _Backend()


# ==================== Request Queue and Buffer ====================
# Request queue adapter will be assigned during initialization wiring
request_queue = None

# Buffer to store latest results per device
# Structure: {dev_eui: {sensor_type: {"ok": bool, "data": {...}, "error": str, "timestamp": float}}}
buffer = {}
buffer_lock = threading.Lock()


def get_buffer_data(dev_eui: str, sensor: str) -> Optional[Dict[str, Any]]:
    """
    Safely get latest buffer data for a device and sensor.
    
    Args:
        dev_eui: Device EUI
        sensor: Sensor type ("ht", "ta", "wl", "mmwave")
    
    Returns:
        dict: {"ok": bool, "data": {...}, "error": str, "timestamp": float} or None
    """
    with buffer_lock:
        if dev_eui in buffer and sensor in buffer[dev_eui]:
            return buffer[dev_eui][sensor]
    return None


def _error_result(error: str) -> Dict[str, Any]:
    return {
        "ok": False,
        "data": None,
        "error": error,
        "timestamp": time.time(),
    }


def _write_buffer_result(dev_eui: str, sensor: str, result: Dict[str, Any]):
    with buffer_lock:
        if dev_eui not in buffer:
            buffer[dev_eui] = {}
        buffer[dev_eui][sensor] = result


class _DeviceWorker:
    """Single worker type: one worker instance per dev_eui."""

    def __init__(self, dev_eui: str):
        self.dev_eui = dev_eui
        self._queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def enqueue(self, task: Dict[str, Any]):
        self._queue.put(task)

    def _run(self):
        import sensor_service as ss

        dispatch_map: Dict[str, Callable[[str], Dict[str, Any]]] = {
            "ht": ss.execute_read_ht,
            "ta": ss.execute_read_ta,
            "wl": ss.execute_read_wl,
            "mmwave": ss.execute_read_mmwave,
        }

        while True:
            completion_event = None
            task = None
            try:
                task = self._queue.get(timeout=1.0)
                if task is None:
                    break

                completion_event = task.get("completion_event")
                action = task.get("action")
                sensor = task.get("sensor")
                task_dev_eui = task.get("dev_eui")

                if action != "read":
                    raise ValueError(f"Unsupported task action: {action}")
                if task_dev_eui != self.dev_eui:
                    raise ValueError(f"Task dev_eui mismatch: expected {self.dev_eui}, got {task_dev_eui}")
                if sensor not in dispatch_map:
                    raise ValueError(f"Unsupported sensor: {sensor}")

                executor = dispatch_map[sensor]
                result = executor(self.dev_eui)
                if not isinstance(result, dict):
                    result = _error_result("Executor returned invalid result type")

                _write_buffer_result(self.dev_eui, sensor, result)
                print(f"[_DeviceWorker:{self.dev_eui}] Updated buffer {sensor} ok={bool(result.get('ok'))}")

            except queue.Empty:
                continue
            except Exception as e:
                try:
                    if isinstance(task, dict):
                        task_sensor = task.get("sensor")
                        task_dev_eui = task.get("dev_eui")
                        if task_sensor and task_dev_eui:
                            _write_buffer_result(task_dev_eui, task_sensor, _error_result(f"Worker exception: {str(e)}"))
                    print(f"[_DeviceWorker:{self.dev_eui}] Error: {e}")
                except Exception as inner_e:
                    print(f"[_DeviceWorker:{self.dev_eui}] Failed to store error result: {inner_e}")
            finally:
                if completion_event:
                    completion_event.set()


_DEVICE_WORKERS: Dict[str, _DeviceWorker] = {}
_DEVICE_WORKERS_LOCK = threading.Lock()


def _get_device_worker(dev_eui: str) -> _DeviceWorker:
    with _DEVICE_WORKERS_LOCK:
        worker = _DEVICE_WORKERS.get(dev_eui)
        if worker is None:
            worker = _DeviceWorker(dev_eui)
            _DEVICE_WORKERS[dev_eui] = worker
        return worker


class _TaskRouterQueue:
    """Queue-like adapter used by sensor_service: routes tasks to per-device worker."""

    def put(self, task: Dict[str, Any]):
        if not isinstance(task, dict):
            raise ValueError("Task must be a dict")

        dev_eui = task.get("dev_eui")
        completion_event = task.get("completion_event")
        sensor = task.get("sensor")

        if not dev_eui or not sensor:
            if completion_event:
                completion_event.set()
            raise ValueError("Task missing required fields: dev_eui/sensor")

        worker = _get_device_worker(str(dev_eui))
        worker.enqueue(task)


_LAST_SEND_TS: Dict[str, float] = {}
_SEND_LOCKS: Dict[str, threading.Lock] = {}
_SEND_LOCKS_GUARD = threading.Lock()


def _get_send_lock(dev_eui: str) -> threading.Lock:
    with _SEND_LOCKS_GUARD:
        lock = _SEND_LOCKS.get(dev_eui)
        if lock is None:
            lock = threading.Lock()
            _SEND_LOCKS[dev_eui] = lock
        return lock

# Track last response timestamp per device to avoid reusing responses
_LAST_RESPONSE_TS: Dict[str, float] = {}
_RESPONSE_TS_LOCK = threading.Lock()

# ==================== Per-DTU Inflight Lock ====================
# Ensures that send_and_wait() for the same devEUI runs serially,
# preventing multiple requests from competing for the same uplink response.
_INFLIGHT_LOCKS: Dict[str, threading.Lock] = {}
_INFLIGHT_LOCKS_GUARD = threading.Lock()

def _get_inflight_lock(dev_eui: str) -> threading.Lock:
    """Get or create the per-DTU inflight lock."""
    with _INFLIGHT_LOCKS_GUARD:
        lock = _INFLIGHT_LOCKS.get(dev_eui)
        if lock is None:
            lock = threading.Lock()
            _INFLIGHT_LOCKS[dev_eui] = lock
        return lock


# ==================== Public API ====================

def get_token() -> str:
    """Get authentication token (route to backend)."""
    return _backend.get_token()


def send_request(
    device_id: str,
    data_to_send: str,
    auth_token: str,
    fport: int = 1,
    reference: str = "downlink-cmd",
    min_interval_sec: float = 1.0,
    timeout: float = 30.0
) -> Tuple[int, Optional[Any]]:
    """
    Send downlink with per-DTU rate limiting.

    Args:
        device_id: Device EUI
        data_to_send: Hex string to send
        auth_token: Authentication token
        fport: LoRaWAN fPort
        reference: Reference identifier
        min_interval_sec: Minimum interval (seconds) between sends to this DTU
        timeout: Timeout in seconds for waiting on send completion

    Returns:
        tuple: (status, response)
    """
    send_lock = _get_send_lock(device_id)
    with send_lock:
        last_send_ts = _LAST_SEND_TS.get(device_id, 0.0)
        elapsed = time.time() - last_send_ts
        if elapsed < min_interval_sec:
            time.sleep(min_interval_sec - elapsed)
        _LAST_SEND_TS[device_id] = time.time()
        return _backend.send_request(device_id, data_to_send, auth_token, fport, reference)


def pull_latest_data(
    device_id: str,
    auth_token: str,
    size: int = 10
) -> Tuple[int, Optional[str]]:
    """
    Pull latest uplink data (for mmWave sensor compatibility).

    Args:
        device_id: Device EUI
        auth_token: Authentication token
        size: Number of uplinks to retrieve

    Returns:
        tuple: (status, hex_string) - returns the most recent uplink hex data
    """
    status, uplinks = pull_latest_uplinks(device_id, auth_token, size)
    if status != 1 or not uplinks:
        return (0, None)
    # Return the most recent uplink's hex data
    return (1, uplinks[0]["hex"])


def pull_latest_uplinks(
    device_id: str,
    auth_token: str,
    size: int = 10
) -> Tuple[int, Optional[List[Dict[str, Any]]]]:
    """
    Pull latest uplinks with timestamp info.

    Returns:
        tuple: (status, list of {ts, fport, hex, raw})
    """
    return _backend.pull_latest_uplinks(device_id, auth_token, size)


def send_and_wait(
    device_id: str,
    data_to_send: str,
    auth_token: str,
    response_validator: Callable[[str], bool],
    timeout_sec: float = 30.0,
    fport: int = 1,
    reference: str = "downlink-cmd",
    min_interval_sec: float = 1.0,
    poll_interval_sec: float = 1.0
) -> Tuple[int, Optional[str]]:
    """
    Send request and wait for matching response.
    
    Uses per-DTU inflight lock to ensure that requests to the same device_id
    are processed serially (send + wait + consume), preventing response mismatching
    when multiple threads are sending to the same DTU.

    Args:
        device_id: Device EUI
        data_to_send: Hex string to send
        auth_token: Auth token
        response_validator: Callable that returns True if uplink is the response for this request
        timeout_sec: Timeout in seconds
        fport: LoRaWAN fPort for downlink
        reference: Reference identifier
        min_interval_sec: Minimum interval between sends to this DTU
        poll_interval_sec: Interval between uplink polls

    Returns:
        tuple: (status, hex_response_string) or (0, None) on timeout/failure
    """
    # Acquire per-DTU inflight lock to serialize send+wait for same device
    lock = _get_inflight_lock(device_id)
    
    with lock:
        # Send the request
        send_time = time.time()
        status, response = send_request(
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
            return (0, None)

        # Poll for response
        deadline = send_time + timeout_sec
        while time.time() < deadline:
            time.sleep(poll_interval_sec)

            status, uplinks = pull_latest_uplinks(device_id, auth_token, size=20)
            if status != 1 or uplinks is None:
                continue

            # Filter uplinks: only after send_time AND after last response timestamp, and pass validator
            for uplink in uplinks:
                # Re-read last_resp_ts for each uplink to catch updates from other threads
                with _RESPONSE_TS_LOCK:
                    last_resp_ts = _LAST_RESPONSE_TS.get(device_id, 0.0)
                
                if uplink["ts"] <= last_resp_ts:
                    continue  # Already used this response before
                if uplink["ts"] < send_time:
                    continue  # Too old

                hex_data = uplink["hex"]
                try:
                    if response_validator(hex_data):
                        # Mark this response as used (atomic check-and-set)
                        with _RESPONSE_TS_LOCK:
                            # Double-check: another thread might have used it while we were validating
                            if uplink["ts"] <= _LAST_RESPONSE_TS.get(device_id, 0.0):
                                continue
                            _LAST_RESPONSE_TS[device_id] = uplink["ts"]
                        return (1, hex_data)
                except Exception as e:
                    print(f"[send_and_wait] Validator error: {e}")
                    continue

        print(f"[send_and_wait] Timeout waiting for response from {device_id}")
        return (0, None)


# ==================== Initialize Service Wiring ====================

def _initialize_service():
    """Initialize sensor_service with references to queue and communicator."""
    try:
        import sensor_service as ss
        ss.init(request_queue, __import__(__name__))
    except ImportError:
        print("[initialize_service] sensor_service not yet available, will retry later")


# Queue adapter routes each task to its per-device worker
request_queue = _TaskRouterQueue()

# Initialize sensor service
_initialize_service()



