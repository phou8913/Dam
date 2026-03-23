"""End-to-end connectivity test entrypoint."""

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict

from tools.common_check import (
    authenticate,
    build_reference,
    choose_base_url,
    classify_target,
    queue_downlink,
)
from tools.client_server_check import ClientServerCheck
from tools.dtu_sensor_check import DtuSensorCheck
from tools.gateway_dtu_check import GatewayDtuCheck

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

def _not_run(reason: str) -> Dict[str, Any]:
    return {
        "result": "NOT_RUN",
        "reason": reason,
    }


@dataclass
class SegmentContext:
    base_url: str
    account: str
    password: str
    device_id: str
    application_id: str
    auth_timeout: float
    queue_timeout: float
    ack_timeout: float
    uplink_timeout: float
    poll_interval: float
    uplink_page_size: int
    request_data_hex: str
    request_fport: int
    reference: str
    mqtt_host: str
    mqtt_port: int
    mqtt_username: str
    mqtt_password: str
    mqtt_client_id: str
    mqtt_keepalive: int
    mqtt_tls: bool


FAULT_LABELS = {
    "client_server": "client -> server",
    "gateway_dtu": "server/platform -> gateway -> dtu",
    "dtu_sensor": "dtu -> sensor",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the full end-to-end connectivity check")
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

    parser.add_argument("--request-data-hex", default="010400000003B00B")
    parser.add_argument("--request-fport", type=int, default=1)
    parser.add_argument("--reference", default="")

    parser.add_argument("--mqtt-host", default=DEFAULT_MQTT_HOST)
    parser.add_argument("--mqtt-port", type=int, default=int(DEFAULT_MQTT_PORT))
    parser.add_argument("--mqtt-username", default=DEFAULT_MQTT_USERNAME)
    parser.add_argument("--mqtt-password", default=DEFAULT_MQTT_PASSWORD)
    parser.add_argument("--mqtt-client-id", default=DEFAULT_MQTT_CLIENT_ID)
    parser.add_argument("--mqtt-keepalive", type=int, default=int(DEFAULT_MQTT_KEEPALIVE))
    parser.add_argument("--mqtt-tls", action="store_true")

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print full per-segment details instead of the summarized end-to-end view.",
    )
    return parser.parse_args()


def _build_context(args: argparse.Namespace) -> SegmentContext:
    return SegmentContext(
        base_url=args.base_url,
        account=args.account,
        password=args.password,
        device_id=args.device_id,
        application_id=args.application_id,
        auth_timeout=args.auth_timeout,
        queue_timeout=args.queue_timeout,
        ack_timeout=args.ack_timeout,
        uplink_timeout=args.uplink_timeout,
        poll_interval=args.poll_interval,
        uplink_page_size=args.uplink_page_size,
        request_data_hex=args.request_data_hex,
        request_fport=args.request_fport,
        reference=args.reference,
        mqtt_host=args.mqtt_host,
        mqtt_port=args.mqtt_port,
        mqtt_username=args.mqtt_username,
        mqtt_password=args.mqtt_password,
        mqtt_client_id=args.mqtt_client_id,
        mqtt_keepalive=args.mqtt_keepalive,
        mqtt_tls=args.mqtt_tls,
    )


def _infer_fault_location(results: Dict[str, Dict[str, Any]]) -> str:
    if results["client_server"].get("result") != "PASS":
        return "client -> server"
    if results["gateway_dtu"].get("result") != "PASS":
        return "server/platform -> gateway -> dtu"
    if results["dtu_sensor"].get("result") != "PASS":
        return "dtu -> sensor"
    return "none"


def _build_output(
    *,
    success: bool,
    inferred: str,
    failed_segment: str | None,
    ctx: SegmentContext,
    shared_auth_result: Dict[str, Any],
    results: Dict[str, Dict[str, Any]],
    verbose: bool,
) -> Dict[str, Any]:
    output = {
        "result": "PASS" if success else "FAIL",
        "stage": "end_to_end",
        "selected_segments": ["client_server", "gateway_dtu", "dtu_sensor"],
        "target": classify_target(ctx.base_url),
        "base_url": ctx.base_url,
        "device_id": ctx.device_id,
        "application_id": ctx.application_id,
        "auth_reused": True,
        "auth": {
            "ok": shared_auth_result.get("ok"),
            "status_code": shared_auth_result.get("status_code"),
            "elapsed_ms": shared_auth_result.get("elapsed_ms"),
        },
        "failed_segment": failed_segment,
        "suspected_fault_segment": inferred,
    }

    if verbose:
        output["client_server"] = results["client_server"]
        output["gateway_dtu"] = results["gateway_dtu"]
        output["dtu_sensor"] = results["dtu_sensor"]
        return output

    output["client_server"] = ClientServerCheck.summarize(results["client_server"])
    output["gateway_dtu"] = GatewayDtuCheck.summarize(results["gateway_dtu"])
    output["dtu_sensor"] = DtuSensorCheck.summarize(results["dtu_sensor"])
    return output


def _client_server_auth_fail(ctx: SegmentContext, auth_result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "result": "FAIL",
        "stage": "client_server",
        "target": classify_target(ctx.base_url),
        "base_url": ctx.base_url,
        "device_id": ctx.device_id,
        "auth": auth_result,
    }


def run_end_to_end(ctx: SegmentContext, verbose: bool = False) -> Dict[str, Any]:
    # Reuse one auth result and one shared reference across all three segments.
    shared_auth_result = authenticate(ctx.base_url, ctx.account, ctx.password, ctx.auth_timeout)
    shared_reference = ctx.reference or build_reference("connectivity-test")
    common_kwargs = {
        "base_url": ctx.base_url,
        "account": ctx.account,
        "password": ctx.password,
        "device_id": ctx.device_id,
        "data_hex": ctx.request_data_hex,
        "fport": ctx.request_fport,
        "reference": shared_reference,
        "auth_timeout": ctx.auth_timeout,
        "queue_timeout": ctx.queue_timeout,
        "shared_auth_result": shared_auth_result,
    }
    client_check = ClientServerCheck(
        **common_kwargs,
    )
    gateway_check = GatewayDtuCheck(
        **common_kwargs,
        application_id=ctx.application_id,
        ack_timeout=ctx.ack_timeout,
        mqtt_host=ctx.mqtt_host,
        mqtt_port=ctx.mqtt_port,
        mqtt_username=ctx.mqtt_username,
        mqtt_password=ctx.mqtt_password,
        mqtt_client_id=ctx.mqtt_client_id,
        mqtt_keepalive=ctx.mqtt_keepalive,
        mqtt_tls=ctx.mqtt_tls,
    )
    sensor_check = DtuSensorCheck(
        **common_kwargs,
        uplink_timeout=ctx.uplink_timeout,
        poll_interval=ctx.poll_interval,
        uplink_page_size=ctx.uplink_page_size,
    )
    results: Dict[str, Dict[str, Any]] = {
        "client_server": _not_run("Not reached yet"),
        "gateway_dtu": _not_run("Not reached yet"),
        "dtu_sensor": _not_run("Not reached yet"),
    }

    # 1. Stop immediately if authentication fails.
    if not shared_auth_result.get("ok"):
        results["client_server"] = _client_server_auth_fail(ctx, shared_auth_result)
        results["gateway_dtu"] = _not_run("Skipped because client -> server authentication failed")
        results["dtu_sensor"] = _not_run("Skipped because client -> server authentication failed")
        return _build_output(
            success=False,
            inferred=_infer_fault_location(results),
            failed_segment=FAULT_LABELS["client_server"],
            ctx=ctx,
            shared_auth_result=shared_auth_result,
            results=results,
            verbose=verbose,
        )

    # 2. Stop if there is no downlink payload to send.
    if not ctx.request_data_hex:
        results["client_server"] = {
            "result": "FAIL",
            "stage": "client_server",
            "target": classify_target(ctx.base_url),
            "base_url": ctx.base_url,
            "device_id": ctx.device_id,
            "reason": "request_data_hex is required for the full end-to-end check",
        }
        results["gateway_dtu"] = _not_run("Skipped because request_data_hex is empty")
        results["dtu_sensor"] = _not_run("Skipped because request_data_hex is empty")
        return _build_output(
            success=False,
            inferred=_infer_fault_location(results),
            failed_segment=FAULT_LABELS["client_server"],
            ctx=ctx,
            shared_auth_result=shared_auth_result,
            results=results,
            verbose=verbose,
        )

    # 3. Prepare the ACK listener before sending the shared request.
    prepared_gateway = gateway_check.prepare_ack_monitor(
        auth_result=shared_auth_result,
        reference=shared_reference,
    )
    if not prepared_gateway.get("ok"):
        results["client_server"] = _not_run("Stopped before queue submission")
        results["gateway_dtu"] = {
            "result": "FAIL",
            "stage": "gateway_dtu",
            "base_url": ctx.base_url,
            "application_id": ctx.application_id,
            "device_id": ctx.device_id,
            "auth": {
                "ok": True,
                "status_code": shared_auth_result.get("status_code"),
                "elapsed_ms": shared_auth_result.get("elapsed_ms"),
            },
            "mqtt": prepared_gateway.get("mqtt_result"),
        }
        results["dtu_sensor"] = _not_run("Skipped because server/platform -> gateway -> dtu failed")
        return _build_output(
            success=False,
            inferred=_infer_fault_location(results),
            failed_segment=FAULT_LABELS["gateway_dtu"],
            ctx=ctx,
            shared_auth_result=shared_auth_result,
            results=results,
            verbose=verbose,
        )

    # 4. Capture the current uplink state before sending the shared request.
    prepared_sensor = sensor_check.prepare_uplink_check(
        auth_result=shared_auth_result,
        reference=shared_reference,
    )
    trigger_start_ts = time.time()

    # 5. Send one shared downlink request for the whole end-to-end check.
    shared_queue_result = queue_downlink(
        ctx.base_url,
        ctx.device_id,
        shared_auth_result["token"],
        ctx.request_data_hex,
        ctx.request_fport,
        shared_reference,
        ctx.queue_timeout,
    )

    # 6. Build the client -> server result from the shared queue response.
    results["client_server"] = client_check.finalize_with_queue(
        shared_auth_result,
        shared_queue_result,
        shared_reference,
    )
    if results["client_server"].get("result") != "PASS":
        listener = prepared_gateway.get("listener")
        if listener is not None:
            listener.stop()
        results["gateway_dtu"] = _not_run("Skipped because client -> server failed")
        results["dtu_sensor"] = _not_run("Skipped because client -> server failed")
        return _build_output(
            success=False,
            inferred=_infer_fault_location(results),
            failed_segment=FAULT_LABELS["client_server"],
            ctx=ctx,
            shared_auth_result=shared_auth_result,
            results=results,
            verbose=verbose,
        )

    # 7. Finalize the gateway -> DTU result using the ACK outcome.
    results["gateway_dtu"] = gateway_check.finalize_with_queue(
        prepared_gateway,
        shared_queue_result,
    )
    if results["gateway_dtu"].get("result") != "PASS":
        results["dtu_sensor"] = _not_run("Skipped because server/platform -> gateway -> dtu failed")
        return _build_output(
            success=False,
            inferred=_infer_fault_location(results),
            failed_segment=FAULT_LABELS["gateway_dtu"],
            ctx=ctx,
            shared_auth_result=shared_auth_result,
            results=results,
            verbose=verbose,
        )

    # 8. Finalize the DTU -> sensor result using the observed uplinks.
    results["dtu_sensor"] = sensor_check.finalize_with_queue(
        prepared_sensor,
        shared_queue_result,
        trigger_start_ts,
    )
    return _build_output(
        success=results["dtu_sensor"].get("result") == "PASS",
        inferred=_infer_fault_location(results),
        failed_segment=None if results["dtu_sensor"].get("result") == "PASS" else FAULT_LABELS["dtu_sensor"],
        ctx=ctx,
        shared_auth_result=shared_auth_result,
        results=results,
        verbose=verbose,
    )


def main() -> int:
    args = _parse_args()
    ctx = _build_context(args)
    output = run_end_to_end(ctx, verbose=args.verbose)
    print(json.dumps(output, indent=2))
    return 0 if output.get("result") == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
