"""
Sensor Service Layer
Encapsulates sensor reading logic: request queuing and execution.
Responsible for:
  - request_*(): Queue a read request (called by GUI)
  - execute_*(): Execute the read (called by communicator worker)
"""

import time
import threading
from datetime import datetime
from typing import Dict, Any, Callable

# Sensor profiles
from humidity_temp_sensor import HumidityTempSensor
from tilt_acc_sensor import HWT901BSensor
from water_level_sensor import WaterLevelSensor
from mmwave_sensor import MMWaveSensor

# Will be set by communicator
_request_queue = None
_communicator_module = None


def _log_terminal(message: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")


def _log_read_start(sensor_title: str):
    _log_terminal(f"\n--- {sensor_title} ---")
    _log_terminal("Read request queued, waiting for response...")


def _log_read_result(sensor: str, result: Dict[str, Any]):
    if not result or not result.get("ok"):
        error_msg = (result or {}).get("error", "No data available")
        if str(error_msg).startswith("Timeout:"):
            _log_terminal(str(error_msg))
        else:
            _log_terminal(f"Failed to read: {error_msg}")
        return

    data = result.get("data") or {}

    if sensor == "ht":
        _log_terminal(f"Temperature: {data['temperature_c']:.2f} °C")
        _log_terminal(f"Humidity: {data['humidity_rh']:.2f} %RH")
        _log_terminal(f"Dewpoint: {data['dewpoint_c']:.2f} °C")
        _log_terminal(f"CRC Valid: {data['crc_valid']}")
        _log_terminal(f"Raw: {data['raw_hex']}")
    elif sensor == "ta":
        _log_terminal(f"Roll: {data['roll']:.2f}°")
        _log_terminal(f"Pitch: {data['pitch']:.2f}°")
        _log_terminal(f"Yaw: {data['yaw']:.2f}°")
        _log_terminal(f"Ax: {data['ax_g']:.3f}g ({data['ax_ms2']:.2f} m/s²)")
        _log_terminal(f"Ay: {data['ay_g']:.3f}g ({data['ay_ms2']:.2f} m/s²)")
        _log_terminal(f"Az: {data['az_g']:.3f}g ({data['az_ms2']:.2f} m/s²)")
        _log_terminal(f"Raw: {data['raw_hex']}")
    elif sensor == "wl":
        _log_terminal(f"Water Level: {data['level_m']:.3f} m")
        _log_terminal(f"CRC Valid: {data['crc_valid']}")
        _log_terminal(f"Raw: {data['raw_hex']}")
    elif sensor == "mmwave":
        targets_dict = data.get("targets", {})
        if targets_dict:
            _log_terminal(f"Detected {len(targets_dict)} targets:")
            for name, target_data in targets_dict.items():
                angle, distance = target_data
                _log_terminal(f"  {name}: {angle:.1f}° @ {distance:.2f}m")
        else:
            _log_terminal("No targets detected")

    updated_at = datetime.fromtimestamp(result.get("timestamp", time.time())).strftime("%H:%M:%S")
    _log_terminal(f"Updated at: {updated_at}")


def _read_with_logging(
    sensor_key: str,
    sensor_title: str,
    request_func: Callable[[str], threading.Event],
    dev_eui: str,
    timeout: float,
) -> Dict[str, Any]:
    _log_read_start(sensor_title)
    try:
        event = request_func(dev_eui)
        result = _wait_and_get_result(dev_eui, sensor_key, event, timeout)
    except Exception as e:
        result = {
            "ok": False,
            "data": None,
            "error": str(e),
            "timestamp": time.time(),
        }

    _log_read_result(sensor_key, result)
    return result


def init(request_queue, communicator_module):
    """Initialize service with queue and communicator references."""
    global _request_queue, _communicator_module
    _request_queue = request_queue
    _communicator_module = communicator_module


def _ensure_initialized():
    """Ensure service is initialized, auto-binding communicator on first use."""
    global _request_queue, _communicator_module

    if _request_queue is not None and _communicator_module is not None:
        return

    try:
        import communicator as comm
        if _request_queue is None:
            _request_queue = getattr(comm, "request_queue", None)
        if _communicator_module is None:
            _communicator_module = comm
    except Exception:
        pass

    if _request_queue is None or _communicator_module is None:
        raise RuntimeError("Service not initialized")


# ==================== Request Functions (called by GUI) ====================

def request_read_ht(dev_eui: str) -> threading.Event:
    """Queue a humidity/temperature read request. Returns an Event that signals completion."""
    _ensure_initialized()
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
    _ensure_initialized()
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
    _ensure_initialized()
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
    _ensure_initialized()
    event = threading.Event()
    _request_queue.put({
        "sensor": "mmwave",
        "dev_eui": dev_eui,
        "timestamp": time.time(),
        "completion_event": event
    })
    return event


def _wait_and_get_result(dev_eui: str, sensor: str, completion_event: threading.Event, timeout: float = 20.0) -> Dict[str, Any]:
    """
    Wait for queued read completion and return latest buffered result.
    Returns: {"ok": bool, "data": any, "error": str|None, "timestamp": float}
    """
    try:
        _ensure_initialized()
    except Exception as e:
        return {
            "ok": False,
            "data": None,
            "error": str(e),
            "timestamp": time.time()
        }

    completed = completion_event.wait(timeout=timeout)
    if not completed:
        return {
            "ok": False,
            "data": None,
            "error": f"Timeout: no response after {int(timeout)} seconds",
            "timestamp": time.time()
        }

    result = _communicator_module.get_buffer_data(dev_eui, sensor)
    if result is None:
        return {
            "ok": False,
            "data": None,
            "error": "No data available",
            "timestamp": time.time()
        }
    return result


def read_ht(dev_eui: str, timeout: float = 20.0) -> Dict[str, Any]:
    """Queue humidity/temperature read and return final result dict."""
    return _read_with_logging("ht", "Humidity/Temperature Sensor", request_read_ht, dev_eui, timeout)


def read_ta(dev_eui: str, timeout: float = 20.0) -> Dict[str, Any]:
    """Queue tilt/acceleration read and return final result dict."""
    return _read_with_logging("ta", "Tilt/Acceleration Sensor", request_read_ta, dev_eui, timeout)


def read_wl(dev_eui: str, timeout: float = 20.0) -> Dict[str, Any]:
    """Queue water-level read and return final result dict."""
    return _read_with_logging("wl", "Water Level Sensor", request_read_wl, dev_eui, timeout)


def read_mmwave(dev_eui: str, timeout: float = 20.0) -> Dict[str, Any]:
    """Queue mmWave read and return final result dict."""
    return _read_with_logging("mmwave", "mmWave Radar Sensor", request_read_mmwave, dev_eui, timeout)


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
