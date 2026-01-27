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


# ==================== Determine Backend ====================
USE_FAKE_DTU = os.getenv("USE_FAKE_DTU") == "1"

if USE_FAKE_DTU:
    import fake_communicator as _backend
else:
    class _RealBackend:
        """Real LoRa API communicator"""
        import requests

        BASE_URL = "http://99.10.226.29:4560/api"
        ACCOUNT = "admin"
        PASSWORD = "admin"

        @staticmethod
        def get_token() -> str:
            """Authenticate with the API and retrieve JWT token."""
            url = f"{_RealBackend.BASE_URL}/v1/internal/auth"
            payload = {
                "account": _RealBackend.ACCOUNT,
                "password": _RealBackend.PASSWORD
            }
            try:
                response = _RealBackend.requests.post(url, json=payload)
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
                url = f"{_RealBackend.BASE_URL}/v1/devices/{device_id}/queue"
                headers = {
                    "token": auth_token,
                    "content-type": "application/json"
                }
                payload = {
                    "confirmed": False,
                    "mode": "hex",
                    "data": data_to_send,
                    "fPort": fport,
                    "reference": reference
                }
                response = _RealBackend.requests.post(url, json=payload, headers=headers)
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
                url = f"{_RealBackend.BASE_URL}/v1/uplink-storage/devices/{device_id}/uplink"
                headers = {"token": auth_token}
                params = {"size": size, "page": 1}
                response = _RealBackend.requests.get(url, headers=headers, params=params)
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

    _backend = _RealBackend()


# ==================== Per-DTU Rate Limiter ====================
class DTUQueue:
    """
    Per-DTU message queue with rate limiting.
    Ensures minimum interval between consecutive sends to same DTU.
    """

    def __init__(self, dev_eui: str, min_interval_sec: float = 1.0):
        self.dev_eui = dev_eui
        self.min_interval_sec = min_interval_sec
        self._queue = queue.Queue()
        self._last_send_time = 0.0
        self._lock = threading.Lock()
        self._worker_thread = threading.Thread(target=self._worker, daemon=True)
        self._worker_thread.start()

    def _worker(self):
        """Worker thread: process queue with rate limiting."""
        while True:
            try:
                task = self._queue.get(timeout=0.1)
                if task is None:
                    break

                send_func, send_args, send_kwargs, result_holder, completion_event = task

                with self._lock:
                    elapsed = time.time() - self._last_send_time
                    if elapsed < self.min_interval_sec:
                        time.sleep(self.min_interval_sec - elapsed)
                    self._last_send_time = time.time()

                try:
                    result = send_func(*send_args, **send_kwargs)
                    result_holder["result"] = result
                    result_holder["error"] = None
                except Exception as e:
                    result_holder["result"] = None
                    result_holder["error"] = str(e)
                finally:
                    completion_event.set()

            except queue.Empty:
                continue

    def send(self, send_func: Callable, *args, timeout: float = 30.0, **kwargs) -> Tuple[int, Optional[Any]]:
        """
        Queue a send operation and wait for result.

        Args:
            send_func: Function to execute
            timeout: Timeout in seconds for waiting on result
            *args, **kwargs: Arguments to pass to send_func

        Returns:
            tuple: (status, response) from send_func
        """
        result_holder = {"result": None, "error": None}
        completion_event = threading.Event()
        self._queue.put((send_func, args, kwargs, result_holder, completion_event))

        if completion_event.wait(timeout):
            if result_holder["error"]:
                return (0, None)
            return result_holder["result"]
        else:
            return (0, None)


# Global DTU queues
_DTU_QUEUES: Dict[str, DTUQueue] = {}
_QUEUE_LOCK = threading.Lock()


def _get_dtu_queue(dev_eui: str, min_interval_sec: float = 1.0) -> DTUQueue:
    """Get or create DTU queue."""
    with _QUEUE_LOCK:
        if dev_eui not in _DTU_QUEUES:
            _DTU_QUEUES[dev_eui] = DTUQueue(dev_eui, min_interval_sec)
        return _DTU_QUEUES[dev_eui]


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
    queue = _get_dtu_queue(device_id, min_interval_sec)

    def _do_send():
        return _backend.send_request(device_id, data_to_send, auth_token, fport, reference)

    return queue.send(_do_send, timeout=timeout)


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
    if USE_FAKE_DTU:
        # Call fake backend's pull_latest_uplinks directly to preserve real timestamps
        return _backend.pull_latest_uplinks(device_id, auth_token, size)
    else:
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

        # Filter uplinks: only after send_time, and pass validator
        for uplink in uplinks:
            if uplink["ts"] < send_time:
                continue  # Too old

            hex_data = uplink["hex"]
            try:
                if response_validator(hex_data):
                    return (1, hex_data)
            except Exception as e:
                print(f"[send_and_wait] Validator error: {e}")
                continue

    print(f"[send_and_wait] Timeout waiting for response from {device_id}")
    return (0, None)


