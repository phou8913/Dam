"""
Sensor Service Layer
Encapsulates sensor reading logic: request queuing and execution.
Responsible for:
  - request_*(): Queue a read request (called by GUI)
  - execute_*(): Execute the read (called by communicator worker)
"""

import time
import queue as queue_module
import threading
from typing import Dict, Any, Optional, Tuple

# Sensor profiles
from humidity_temp_sensor import HumidityTempSensor
from tilt_acc_sensor import HWT901BSensor
from water_level_sensor import WaterLevelSensor
from mmwave_sensor import MMWaveSensor

# Will be set by communicator
_request_queue = None
_communicator_module = None


def init(request_queue, communicator_module):
    """Initialize service with queue and communicator references."""
    global _request_queue, _communicator_module
    _request_queue = request_queue
    _communicator_module = communicator_module


# ==================== Request Functions (called by GUI) ====================

def request_read_ht(dev_eui: str) -> threading.Event:
    """Queue a humidity/temperature read request. Returns an Event that signals completion."""
    if _request_queue is None:
        raise RuntimeError("Service not initialized")
    event = threading.Event()
    _request_queue.put({
        "sensor": "ht",
        "dev_eui": dev_eui,
        "timestamp": time.time(),
        "completion_event": event
    })
    return event


def request_read_ta(dev_eui: str) -> threading.Event:
    """Queue a tilt/acceleration read request. Returns an Event that signals completion."""
    if _request_queue is None:
        raise RuntimeError("Service not initialized")
    event = threading.Event()
    _request_queue.put({
        "sensor": "ta",
        "dev_eui": dev_eui,
        "timestamp": time.time(),
        "completion_event": event
    })
    return event


def request_read_wl(dev_eui: str) -> threading.Event:
    """Queue a water level read request. Returns an Event that signals completion."""
    if _request_queue is None:
        raise RuntimeError("Service not initialized")
    event = threading.Event()
    _request_queue.put({
        "sensor": "wl",
        "dev_eui": dev_eui,
        "timestamp": time.time(),
        "completion_event": event
    })
    return event


def request_read_mmwave(dev_eui: str) -> threading.Event:
    """Queue a mmWave radar read request. Returns an Event that signals completion."""
    if _request_queue is None:
        raise RuntimeError("Service not initialized")
    event = threading.Event()
    _request_queue.put({
        "sensor": "mmwave",
        "dev_eui": dev_eui,
        "timestamp": time.time(),
        "completion_event": event
    })
    return event


# ==================== Execute Functions (called by communicator worker) ====================

def execute_read_ht(dev_eui: str) -> Dict[str, Any]:
    """
    Execute humidity/temperature read.
    Returns: {"ok": bool, "data": {...}, "error": str or None, "timestamp": float}
    """
    try:
        profile = HumidityTempSensor()
        token = _communicator_module.get_token()
        cmd_hex = profile.encode_read_command()

        status, hex_data = _communicator_module.send_and_wait(
            device_id=dev_eui,
            data_to_send=cmd_hex,
            auth_token=token,
            response_validator=profile.validate_response,
            timeout_sec=15.0,
            fport=1,
            reference="humidity-read",
            min_interval_sec=1.0,
            poll_interval_sec=1.0
        )

        if status != 1 or not hex_data:
            return {
                "ok": False,
                "data": None,
                "error": "Failed to get response or timeout",
                "timestamp": time.time()
            }

        decoded = profile.decode_response(hex_data)
        if decoded:
            return {
                "ok": True,
                "data": decoded,
                "error": None,
                "timestamp": time.time()
            }
        else:
            return {
                "ok": False,
                "data": None,
                "error": "Failed to decode response",
                "timestamp": time.time()
            }

    except Exception as e:
        return {
            "ok": False,
            "data": None,
            "error": str(e),
            "timestamp": time.time()
        }


def execute_read_ta(dev_eui: str) -> Dict[str, Any]:
    """
    Execute tilt/acceleration read.
    Returns: {"ok": bool, "data": {...}, "error": str or None, "timestamp": float}
    """
    try:
        profile = HWT901BSensor()
        token = _communicator_module.get_token()

        # Unlock
        unlock_cmd = profile.encode_unlock_command()
        status, _ = _communicator_module.send_request(
            device_id=dev_eui,
            data_to_send=unlock_cmd,
            auth_token=token,
            min_interval_sec=1.0
        )
        if status != 1:
            return {
                "ok": False,
                "data": None,
                "error": "Failed to send unlock command",
                "timestamp": time.time()
            }
        time.sleep(0.5)

        # Read angles
        angles_status, angles_hex = _communicator_module.send_and_wait(
            device_id=dev_eui,
            data_to_send=profile.encode_read_angles_command(),
            auth_token=token,
            response_validator=profile.validate_angles_response,
            timeout_sec=15.0,
            fport=1,
            reference="angles-read",
            min_interval_sec=1.0,
            poll_interval_sec=1.0
        )

        if angles_status != 1 or not angles_hex:
            return {
                "ok": False,
                "data": None,
                "error": "Failed to read angles",
                "timestamp": time.time()
            }

        angles_data = profile.decode_angles(angles_hex)
        if not angles_data:
            return {
                "ok": False,
                "data": None,
                "error": "Failed to decode angles",
                "timestamp": time.time()
            }

        # Read acceleration
        accel_status, accel_hex = _communicator_module.send_and_wait(
            device_id=dev_eui,
            data_to_send=profile.encode_read_accel_command(),
            auth_token=token,
            response_validator=profile.validate_accel_response,
            timeout_sec=15.0,
            fport=1,
            reference="accel-read",
            min_interval_sec=1.0,
            poll_interval_sec=1.0
        )

        if accel_status != 1 or not accel_hex:
            return {
                "ok": False,
                "data": None,
                "error": "Failed to read acceleration",
                "timestamp": time.time()
            }

        accel_data = profile.decode_acceleration(accel_hex)
        if not accel_data:
            return {
                "ok": False,
                "data": None,
                "error": "Failed to decode acceleration",
                "timestamp": time.time()
            }

        # Combine angles and accel
        combined_data = {**angles_data, **accel_data}
        return {
            "ok": True,
            "data": combined_data,
            "error": None,
            "timestamp": time.time()
        }

    except Exception as e:
        return {
            "ok": False,
            "data": None,
            "error": str(e),
            "timestamp": time.time()
        }


def execute_read_wl(dev_eui: str) -> Dict[str, Any]:
    """
    Execute water level read.
    Returns: {"ok": bool, "data": {...}, "error": str or None, "timestamp": float}
    """
    try:
        profile = WaterLevelSensor()
        token = _communicator_module.get_token()
        cmd_hex = profile.encode_read_command()

        status, hex_data = _communicator_module.send_and_wait(
            device_id=dev_eui,
            data_to_send=cmd_hex,
            auth_token=token,
            response_validator=profile.validate_response,
            timeout_sec=15.0,
            fport=1,
            reference="water-level-read",
            min_interval_sec=1.0,
            poll_interval_sec=1.0
        )

        if status != 1 or not hex_data:
            return {
                "ok": False,
                "data": None,
                "error": "Failed to get response or timeout",
                "timestamp": time.time()
            }

        decoded = profile.decode_response(hex_data)
        if decoded:
            return {
                "ok": True,
                "data": decoded,
                "error": None,
                "timestamp": time.time()
            }
        else:
            return {
                "ok": False,
                "data": None,
                "error": "Failed to decode response",
                "timestamp": time.time()
            }

    except Exception as e:
        return {
            "ok": False,
            "data": None,
            "error": str(e),
            "timestamp": time.time()
        }


def execute_read_mmwave(dev_eui: str) -> Dict[str, Any]:
    """
    Execute mmWave radar read (pull only, no downlink).
    Returns: {"ok": bool, "data": {...}, "error": str or None, "timestamp": float}
    """
    try:
        profile = MMWaveSensor()
        token = _communicator_module.get_token()

        status, hex_data = _communicator_module.pull_latest_data(
            device_id=dev_eui,
            auth_token=token,
            size=10
        )

        if status != 1 or not hex_data:
            return {
                "ok": False,
                "data": None,
                "error": "Failed to pull latest uplink",
                "timestamp": time.time()
            }

        targets = profile.decode_targets(hex_data)
        if targets:
            return {
                "ok": True,
                "data": {"targets": targets},
                "error": None,
                "timestamp": time.time()
            }
        else:
            return {
                "ok": False,
                "data": None,
                "error": "No targets detected or failed to decode",
                "timestamp": time.time()
            }

    except Exception as e:
        return {
            "ok": False,
            "data": None,
            "error": str(e),
            "timestamp": time.time()
        }
