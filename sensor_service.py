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


BUNDLED_SENSOR_STEPS: Dict[str, list[str]] = {
    "ht": ["ht_read"],
    "ta": ["ta_unlock", "ta_read_angles", "ta_read_accel"],
    "wl": ["wl_read"],
    "mmwave": ["mmwave_pull"],
}


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


def _queue_read_request(sensor: str, dev_eui: str) -> threading.Event:
    _ensure_initialized()
    event = threading.Event()
    _request_queue.put({
        "action": "read",
        "sensor": sensor,
        "dev_eui": dev_eui,
        "timestamp": time.time(),
        "completion_event": event,
    })
    return event


# ==================== Request Functions (called by GUI) ====================

def request_read_ht(dev_eui: str) -> threading.Event:
    """Queue a humidity/temperature read request. Returns an Event that signals completion."""
    return _queue_read_request("ht", dev_eui)


def request_read_ta(dev_eui: str) -> threading.Event:
    """Queue a tilt/acceleration read request. Returns an Event that signals completion."""
    return _queue_read_request("ta", dev_eui)


def request_read_wl(dev_eui: str) -> threading.Event:
    """Queue a water level read request. Returns an Event that signals completion."""
    return _queue_read_request("wl", dev_eui)


def request_read_mmwave(dev_eui: str) -> threading.Event:
    """Queue a mmWave radar read request. Returns an Event that signals completion."""
    return _queue_read_request("mmwave", dev_eui)


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
    profile = HumidityTempSensor()
    return _execute_ht_bundled_steps(dev_eui, BUNDLED_SENSOR_STEPS["ht"], profile=profile)


def execute_read_ta(dev_eui: str) -> Dict[str, Any]:
    """
    Execute tilt/acceleration read.
    Returns: {"ok": bool, "data": {...}, "error": str or None, "timestamp": float}
    """
    profile = HWT901BSensor()
    return _execute_ta_bundled_steps(dev_eui, BUNDLED_SENSOR_STEPS["ta"], profile=profile)


def execute_read_wl(dev_eui: str) -> Dict[str, Any]:
    """
    Execute water level read.
    Returns: {"ok": bool, "data": {...}, "error": str or None, "timestamp": float}
    """
    profile = WaterLevelSensor()
    return _execute_wl_bundled_steps(dev_eui, BUNDLED_SENSOR_STEPS["wl"], profile=profile)


def execute_read_mmwave(dev_eui: str) -> Dict[str, Any]:
    """
    Execute mmWave radar read (pull only, no downlink).
    Returns: {"ok": bool, "data": {...}, "error": str or None, "timestamp": float}
    """
    profile = MMWaveSensor()
    return _execute_mmwave_bundled_steps(dev_eui, BUNDLED_SENSOR_STEPS["mmwave"], profile=profile)


# ==================== Bundle Step Handlers ====================

def _ta_step_unlock(dev_eui: str, token: str, profile: HWT901BSensor) -> tuple[bool, Any]:
    unlock_cmd = profile.encode_unlock_command()
    status, _ = _communicator_module.send_request(
        device_id=dev_eui,
        data_to_send=unlock_cmd,
        auth_token=token,
        min_interval_sec=1.0,
    )
    if status != 1:
        return False, "Failed to send unlock command"
    time.sleep(0.5)
    return True, None


def _ta_step_read_angles(dev_eui: str, token: str, profile: HWT901BSensor) -> tuple[bool, Any]:
    status, angles_hex = _communicator_module.send_and_wait(
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
        return False, "Failed to read angles"

    angles_data = profile.decode_angles(angles_hex)
    if not angles_data:
        return False, "Failed to decode angles"
    return True, angles_data


def _ta_step_read_accel(dev_eui: str, token: str, profile: HWT901BSensor) -> tuple[bool, Any]:
    status, accel_hex = _communicator_module.send_and_wait(
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
        return False, "Failed to read acceleration"

    accel_data = profile.decode_acceleration(accel_hex)
    if not accel_data:
        return False, "Failed to decode acceleration"
    return True, accel_data


def _execute_ta_bundled_steps(dev_eui: str, steps: list[str], profile: HWT901BSensor | None = None) -> Dict[str, Any]:
    try:
        profile = profile or HWT901BSensor()
        token = _communicator_module.get_token()
        combined_data: Dict[str, Any] = {}

        for step in steps:
            if step == "ta_unlock":
                ok, payload = _ta_step_unlock(dev_eui, token, profile)
            elif step == "ta_read_angles":
                ok, payload = _ta_step_read_angles(dev_eui, token, profile)
            elif step == "ta_read_accel":
                ok, payload = _ta_step_read_accel(dev_eui, token, profile)
            else:
                return {
                    "ok": False,
                    "data": None,
                    "error": f"Unsupported bundle step: {step}",
                    "timestamp": time.time(),
                }

            if not ok:
                return {
                    "ok": False,
                    "data": None,
                    "error": str(payload),
                    "timestamp": time.time(),
                }

            if isinstance(payload, dict):
                combined_data.update(payload)

        return {
            "ok": True,
            "data": combined_data,
            "error": None,
            "timestamp": time.time(),
        }
    except Exception as e:
        return {
            "ok": False,
            "data": None,
            "error": str(e),
            "timestamp": time.time(),
        }


def _ht_step_read(dev_eui: str, token: str, profile: HumidityTempSensor) -> tuple[bool, Any]:
    status, hex_data = _communicator_module.send_and_wait(
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
        return False, "Failed to get response or timeout"

    decoded = profile.decode_response(hex_data)
    if not decoded:
        return False, "Failed to decode response"
    return True, decoded


def _wl_step_read(dev_eui: str, token: str, profile: WaterLevelSensor) -> tuple[bool, Any]:
    status, hex_data = _communicator_module.send_and_wait(
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
        return False, "Failed to get response or timeout"

    decoded = profile.decode_response(hex_data)
    if not decoded:
        return False, "Failed to decode response"
    return True, decoded


def _mmwave_step_pull(dev_eui: str, token: str, profile: MMWaveSensor) -> tuple[bool, Any]:
    status, hex_data = _communicator_module.pull_latest_data(
        device_id=dev_eui,
        auth_token=token,
        size=10,
    )
    if status != 1 or not hex_data:
        return False, "Failed to pull latest uplink"

    targets = profile.decode_targets(hex_data)
    if not targets:
        return False, "No targets detected or failed to decode"
    return True, {"targets": targets}


# ==================== Bundle Step Executors ====================

def _execute_steps(steps: list[str], step_handlers: Dict[str, Callable[[], tuple[bool, Any]]]) -> Dict[str, Any]:
    combined_data: Dict[str, Any] = {}

    for step in steps:
        step_handler = step_handlers.get(step)
        if step_handler is None:
            return {
                "ok": False,
                "data": None,
                "error": f"Unsupported bundle step: {step}",
                "timestamp": time.time(),
            }

        ok, payload = step_handler()
        if not ok:
            return {
                "ok": False,
                "data": None,
                "error": str(payload),
                "timestamp": time.time(),
            }

        if isinstance(payload, dict):
            combined_data.update(payload)

    return {
        "ok": True,
        "data": combined_data,
        "error": None,
        "timestamp": time.time(),
    }


def _execute_ht_bundled_steps(dev_eui: str, steps: list[str], profile: HumidityTempSensor | None = None) -> Dict[str, Any]:
    try:
        profile = profile or HumidityTempSensor()
        token = _communicator_module.get_token()
        step_handlers: Dict[str, Callable[[], tuple[bool, Any]]] = {
            "ht_read": lambda: _ht_step_read(dev_eui, token, profile),
        }
        return _execute_steps(steps, step_handlers)
    except Exception as e:
        return {
            "ok": False,
            "data": None,
            "error": str(e),
            "timestamp": time.time(),
        }


def _execute_wl_bundled_steps(dev_eui: str, steps: list[str], profile: WaterLevelSensor | None = None) -> Dict[str, Any]:
    try:
        profile = profile or WaterLevelSensor()
        token = _communicator_module.get_token()
        step_handlers: Dict[str, Callable[[], tuple[bool, Any]]] = {
            "wl_read": lambda: _wl_step_read(dev_eui, token, profile),
        }
        return _execute_steps(steps, step_handlers)
    except Exception as e:
        return {
            "ok": False,
            "data": None,
            "error": str(e),
            "timestamp": time.time(),
        }


def _execute_mmwave_bundled_steps(dev_eui: str, steps: list[str], profile: MMWaveSensor | None = None) -> Dict[str, Any]:
    try:
        profile = profile or MMWaveSensor()
        token = _communicator_module.get_token()
        step_handlers: Dict[str, Callable[[], tuple[bool, Any]]] = {
            "mmwave_pull": lambda: _mmwave_step_pull(dev_eui, token, profile),
        }
        return _execute_steps(steps, step_handlers)
    except Exception as e:
        return {
            "ok": False,
            "data": None,
            "error": str(e),
            "timestamp": time.time(),
        }


# ==================== Bundle Dispatcher ====================

def execute_bundled_read(task: Dict[str, Any]) -> Dict[str, Any]:
    sensor = task.get("sensor")
    dev_eui = task.get("dev_eui")

    if not dev_eui or not sensor:
        return {
            "ok": False,
            "data": None,
            "error": "Invalid bundled task",
            "timestamp": time.time(),
        }

    sensor_key = str(sensor)
    steps = task.get("steps") or BUNDLED_SENSOR_STEPS.get(sensor_key, [])

    if sensor_key == "ta":
        return _execute_ta_bundled_steps(dev_eui, steps)
    if sensor_key == "ht":
        return _execute_ht_bundled_steps(dev_eui, steps)
    if sensor_key == "wl":
        return _execute_wl_bundled_steps(dev_eui, steps)
    if sensor_key == "mmwave":
        return _execute_mmwave_bundled_steps(dev_eui, steps)

    return {
        "ok": False,
        "data": None,
        "error": f"Bundled execution unsupported for sensor: {sensor_key}",
        "timestamp": time.time(),
    }


