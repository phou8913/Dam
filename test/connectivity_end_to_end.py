"""
End-to-end connectivity orchestrator for:
client -> server -> gateway -> DTU -> sensor

This script runs the three segment tests in order and summarizes where the
chain most likely broke.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from connectivity_common import choose_base_url


SCRIPT_DIR = Path(__file__).resolve().parent
CLIENT_SERVER_SCRIPT = SCRIPT_DIR / "connectivity_client_server.py"
GATEWAY_DTU_SCRIPT = SCRIPT_DIR / "connectivity_gateway_dtu.py"
DTU_SENSOR_SCRIPT = SCRIPT_DIR / "connectivity_dtu_sensor.py"

DEFAULT_BASE_URL = choose_base_url()
DEFAULT_ACCOUNT = os.getenv("LORA_ACCOUNT", "admin")
DEFAULT_PASSWORD = os.getenv("LORA_PASSWORD", "admin")
DEFAULT_DEVICE_ID = os.getenv("DEVICE_ID", "8695311000942380")
DEFAULT_APPLICATION_ID = os.getenv("APPLICATION_ID", "18")
DEFAULT_MQTT_HOST = os.getenv("MQTT_HOST", "99.10.226.29")
DEFAULT_MQTT_PORT = os.getenv("MQTT_PORT", "1883")
DEFAULT_MQTT_USERNAME = os.getenv("MQTT_USERNAME", "mqtt_user_1")
DEFAULT_MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "mqtt_pass_1")
DEFAULT_MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "mqtt_client_1")
DEFAULT_MQTT_KEEPALIVE = os.getenv("MQTT_KEEPALIVE", "60")


def _run_json_script(script_path: Path, args: List[str]) -> Tuple[bool, Dict[str, Any]]:
    command = [sys.executable, str(script_path), *args]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()

    if not stdout:
        return False, {
            "result": "FAIL",
            "error": "No JSON output from child script",
            "command": command,
            "stderr": stderr,
            "returncode": completed.returncode,
        }

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return False, {
            "result": "FAIL",
            "error": f"Failed to parse child JSON output: {exc}",
            "command": command,
            "stdout": stdout,
            "stderr": stderr,
            "returncode": completed.returncode,
        }

    if stderr:
        payload["_stderr"] = stderr
    payload["_returncode"] = completed.returncode
    payload["_command"] = command
    return True, payload


def _client_server_args(args) -> List[str]:
    return [
        "--base-url", args.base_url,
        "--account", args.account,
        "--password", args.password,
        "--device-id", args.device_id,
        "--data-hex", args.client_data_hex,
        "--fport", str(args.client_fport),
        "--reference", args.client_reference,
        "--auth-timeout", str(args.auth_timeout),
        "--queue-timeout", str(args.queue_timeout),
    ]


def _gateway_dtu_args(args) -> List[str]:
    script_args = [
        "--base-url", args.base_url,
        "--account", args.account,
        "--password", args.password,
        "--device-id", args.device_id,
        "--application-id", args.application_id,
        "--data-hex", args.gateway_data_hex,
        "--fport", str(args.gateway_fport),
        "--reference", args.gateway_reference,
        "--auth-timeout", str(args.auth_timeout),
        "--queue-timeout", str(args.queue_timeout),
        "--ack-timeout", str(args.ack_timeout),
        "--mqtt-host", args.mqtt_host,
        "--mqtt-port", str(args.mqtt_port),
        "--mqtt-username", args.mqtt_username,
        "--mqtt-password", args.mqtt_password,
        "--mqtt-client-id", args.mqtt_client_id,
        "--mqtt-keepalive", str(args.mqtt_keepalive),
    ]
    if args.mqtt_tls:
        script_args.append("--mqtt-tls")
    return script_args


def _dtu_sensor_args(args) -> List[str]:
    script_args = [
        "--base-url", args.base_url,
        "--account", args.account,
        "--password", args.password,
        "--device-id", args.device_id,
        "--auth-timeout", str(args.auth_timeout),
        "--queue-timeout", str(args.queue_timeout),
        "--uplink-timeout", str(args.uplink_timeout),
        "--poll-interval", str(args.poll_interval),
        "--uplink-page-size", str(args.uplink_page_size),
    ]
    if args.sensor_data_hex:
        script_args.extend([
            "--data-hex", args.sensor_data_hex,
            "--fport", str(args.sensor_fport),
            "--reference", args.sensor_reference,
        ])
    return script_args


def _infer_fault_location(client_result: Dict[str, Any], gateway_result: Dict[str, Any], sensor_result: Dict[str, Any]) -> str:
    if client_result.get("result") != "PASS":
        return "client -> server"
    if gateway_result.get("result") != "PASS":
        return "server/platform -> gateway -> dtu"
    if sensor_result.get("result") != "PASS":
        return "dtu -> sensor"
    return "none"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run all three connectivity checks and summarize the fault location")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--account", default=DEFAULT_ACCOUNT)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--device-id", default=DEFAULT_DEVICE_ID)
    parser.add_argument("--application-id", default=DEFAULT_APPLICATION_ID)
    parser.add_argument("--auth-timeout", type=float, default=5.0)
    parser.add_argument("--queue-timeout", type=float, default=10.0)
    parser.add_argument("--ack-timeout", type=float, default=20.0)
    parser.add_argument("--uplink-timeout", type=float, default=30.0)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--uplink-page-size", type=int, default=20)

    parser.add_argument("--client-data-hex", default="01")
    parser.add_argument("--client-fport", type=int, default=1)
    parser.add_argument("--client-reference", default="connectivity-test")

    parser.add_argument("--gateway-data-hex", default="01")
    parser.add_argument("--gateway-fport", type=int, default=1)
    parser.add_argument("--gateway-reference", default="")

    parser.add_argument("--sensor-data-hex", default="010400000003B00B")
    parser.add_argument("--sensor-fport", type=int, default=1)
    parser.add_argument("--sensor-reference", default="")

    parser.add_argument("--mqtt-host", default=DEFAULT_MQTT_HOST)
    parser.add_argument("--mqtt-port", type=int, default=int(DEFAULT_MQTT_PORT))
    parser.add_argument("--mqtt-username", default=DEFAULT_MQTT_USERNAME)
    parser.add_argument("--mqtt-password", default=DEFAULT_MQTT_PASSWORD)
    parser.add_argument("--mqtt-client-id", default=DEFAULT_MQTT_CLIENT_ID)
    parser.add_argument("--mqtt-keepalive", type=int, default=int(DEFAULT_MQTT_KEEPALIVE))
    parser.add_argument("--mqtt-tls", action="store_true")
    args = parser.parse_args()

    # Run the client -> server segment first.
    ok_client, client_result = _run_json_script(CLIENT_SERVER_SCRIPT, _client_server_args(args))
    if not ok_client:
        output = {
            "result": "FAIL",
            "stage": "end_to_end",
            "failed_segment": "client_server",
            "suspected_fault_segment": "client -> server",
            "client_server": client_result,
            "gateway_dtu": {
                "result": "NOT_RUN",
                "reason": "Skipped because client -> server failed",
            },
            "dtu_sensor": {
                "result": "NOT_RUN",
                "reason": "Skipped because client -> server failed",
            },
        }
        print(json.dumps(output, indent=2))
        return 1

    if client_result.get("result") != "PASS":
        output = {
            "result": "FAIL",
            "stage": "end_to_end",
            "failed_segment": "client -> server",
            "suspected_fault_segment": "client -> server",
            "client_server": client_result,
            "gateway_dtu": {
                "result": "NOT_RUN",
                "reason": "Skipped because client -> server failed",
            },
            "dtu_sensor": {
                "result": "NOT_RUN",
                "reason": "Skipped because client -> server failed",
            },
        }
        print(json.dumps(output, indent=2))
        return 1

    # Run the gateway -> dtu segment next.
    ok_gateway, gateway_result = _run_json_script(GATEWAY_DTU_SCRIPT, _gateway_dtu_args(args))
    if not ok_gateway:
        output = {
            "result": "FAIL",
            "stage": "end_to_end",
            "failed_segment": "gateway_dtu",
            "suspected_fault_segment": "server/platform -> gateway -> dtu",
            "client_server": client_result,
            "gateway_dtu": gateway_result,
            "dtu_sensor": {
                "result": "NOT_RUN",
                "reason": "Skipped because gateway -> dtu failed",
            },
        }
        print(json.dumps(output, indent=2))
        return 1

    if gateway_result.get("result") != "PASS":
        output = {
            "result": "FAIL",
            "stage": "end_to_end",
            "failed_segment": "server/platform -> gateway -> dtu",
            "suspected_fault_segment": "server/platform -> gateway -> dtu",
            "client_server": client_result,
            "gateway_dtu": gateway_result,
            "dtu_sensor": {
                "result": "NOT_RUN",
                "reason": "Skipped because gateway -> dtu failed",
            },
        }
        print(json.dumps(output, indent=2))
        return 1

    # Run the dtu -> sensor segment last.
    ok_sensor, sensor_result = _run_json_script(DTU_SENSOR_SCRIPT, _dtu_sensor_args(args))
    if not ok_sensor:
        output = {
            "result": "FAIL",
            "stage": "end_to_end",
            "failed_segment": "dtu_sensor",
            "suspected_fault_segment": "dtu -> sensor",
            "client_server": client_result,
            "gateway_dtu": gateway_result,
            "dtu_sensor": sensor_result,
        }
        print(json.dumps(output, indent=2))
        return 1

    end_to_end_success = sensor_result.get("result") == "PASS"
    output = {
        "result": "PASS" if end_to_end_success else "FAIL",
        "stage": "end_to_end",
        "failed_segment": None if end_to_end_success else _infer_fault_location(client_result, gateway_result, sensor_result),
        "suspected_fault_segment": _infer_fault_location(client_result, gateway_result, sensor_result),
        "client_server": client_result,
        "gateway_dtu": gateway_result,
        "dtu_sensor": sensor_result,
    }
    print(json.dumps(output, indent=2))
    return 0 if end_to_end_success else 1


if __name__ == "__main__":
    sys.exit(main())
