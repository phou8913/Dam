"""
LoRa API Communicator
Unified interface for both fake and real LoRa gateway APIs.
- Task queue with a single background worker that decodes tasks and calls the correct API
- Request-response matching with timeout
- Per-DTU inflight lock to prevent response mismatching
"""

import os
import time
import threading
import queue
import base64
import struct
from datetime import datetime
from typing import Optional, Tuple, Any, Dict, Callable, List


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
# Request queue for sensor read tasks
request_queue = queue.Queue()

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


def _buffer_worker():
    """
    Background worker thread that processes sensor read requests from the queue,
    executes them, and updates the buffer.
    """
    # Import here to avoid circular dependency
    import sensor_service as ss

    _SENSOR_EXECUTORS = {
        "ht": ss.execute_read_ht,
        "ta": ss.execute_read_ta,
        "wl": ss.execute_read_wl,
        "mmwave": ss.execute_read_mmwave,
    }

    while True:
        try:
            # Block until a task is available
            task = request_queue.get(timeout=1.0)

            if task is None:  # Poison pill to stop worker
                break

            dev_eui = task.get("dev_eui")
            sensor = task.get("sensor")
            completion_event = task.get("completion_event")

            if not dev_eui or not sensor:
                print("[_buffer_worker] Invalid task, skipping")
                if completion_event:
                    completion_event.set()
                continue

            # Decode task: call the correct API for this sensor type
            execute_fn = _SENSOR_EXECUTORS.get(sensor)
            result = None
            try:
                if execute_fn is None:
                    raise ValueError(f"Unsupported sensor type: {sensor!r} (supported: ht, ta, wl, mmwave)")
                result = execute_fn(dev_eui)
            except Exception as e:
                result = {"ok": False, "data": None, "error": f"Worker exception: {str(e)}", "timestamp": time.time()}

            # Update the data buffer
            if result:
                with buffer_lock:
                    if dev_eui not in buffer:
                        buffer[dev_eui] = {}
                    buffer[dev_eui][sensor] = result
                    print(f"[_buffer_worker] Updated buffer: {dev_eui}/{sensor} ok={result['ok']}")

            # Signal completion to waiting GUI thread
            if completion_event:
                completion_event.set()

        except queue.Empty:
            continue
        except Exception as e:
            print(f"[_buffer_worker] Unexpected error: {e}")


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
    reference: str = "downlink-cmd"
) -> Tuple[int, Optional[Any]]:
    """
    Send downlink to a LoRa device.

    Args:
        device_id: Device EUI
        data_to_send: Hex string to send
        auth_token: Authentication token
        fport: LoRaWAN fPort
        reference: Reference identifier

    Returns:
        tuple: (status, response)
    """
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


# ==================== Initialize and Start Buffer Worker ====================

def _initialize_service():
    """Initialize sensor_service with references to queue and communicator."""
    try:
        import sensor_service as ss
        ss.init(request_queue, __import__(__name__))
    except ImportError:
        print("[initialize_service] sensor_service not yet available, will retry later")


# Start the buffer worker thread as a daemon
_worker_thread = threading.Thread(target=_buffer_worker, daemon=True)
_worker_thread.start()

# Initialize sensor service
_initialize_service()
