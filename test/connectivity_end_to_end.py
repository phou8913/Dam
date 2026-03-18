"""End-to-end connectivity entrypoint using three internal check classes."""

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List

try:
    from .connectivity_common import authenticate, build_reference, choose_base_url, queue_downlink
    from .client_server_check import ClientServerCheck
    from .dtu_sensor_check import DtuSensorCheck
    from .gateway_dtu_check import GatewayDtuCheck
except ImportError:
    from connectivity_common import authenticate, build_reference, choose_base_url, queue_downlink
    from client_server_check import ClientServerCheck
    from dtu_sensor_check import DtuSensorCheck
    from gateway_dtu_check import GatewayDtuCheck

SEGMENT_ORDER = ["client_server", "gateway_dtu", "dtu_sensor"]

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
    client_reference: str
    gateway_reference: str
    sensor_reference: str
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
    parser = argparse.ArgumentParser(description="Run connectivity checks with one orchestrator entrypoint")
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
    parser.add_argument("--client-reference", default="connectivity-test")
    parser.add_argument("--gateway-reference", default="")
    parser.add_argument("--sensor-reference", default="")

    parser.add_argument("--mqtt-host", default=DEFAULT_MQTT_HOST)
    parser.add_argument("--mqtt-port", type=int, default=int(DEFAULT_MQTT_PORT))
    parser.add_argument("--mqtt-username", default=DEFAULT_MQTT_USERNAME)
    parser.add_argument("--mqtt-password", default=DEFAULT_MQTT_PASSWORD)
    parser.add_argument("--mqtt-client-id", default=DEFAULT_MQTT_CLIENT_ID)
    parser.add_argument("--mqtt-keepalive", type=int, default=int(DEFAULT_MQTT_KEEPALIVE))
    parser.add_argument("--mqtt-tls", action="store_true")

    parser.add_argument(
        "--only",
        choices=["all", *SEGMENT_ORDER],
        default="all",
        help="Run all segments or only one selected segment.",
    )
    parser.add_argument(
        "--from-step",
        choices=SEGMENT_ORDER,
        default="client_server",
        help="Start from a later segment when you only want to rerun downstream checks.",
    )
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
        client_reference=args.client_reference,
        gateway_reference=args.gateway_reference,
        sensor_reference=args.sensor_reference,
        mqtt_host=args.mqtt_host,
        mqtt_port=args.mqtt_port,
        mqtt_username=args.mqtt_username,
        mqtt_password=args.mqtt_password,
        mqtt_client_id=args.mqtt_client_id,
        mqtt_keepalive=args.mqtt_keepalive,
        mqtt_tls=args.mqtt_tls,
    )


def _selected_segments(args: argparse.Namespace) -> List[str]:
    if args.only != "all":
        return [args.only]
    start_index = SEGMENT_ORDER.index(args.from_step)
    return SEGMENT_ORDER[start_index:]


def _infer_fault_location(results: Dict[str, Dict[str, Any]]) -> str:
    if results["client_server"].get("result") != "PASS":
        return "client -> server"
    if results["gateway_dtu"].get("result") != "PASS":
        return "server/platform -> gateway -> dtu"
    if results["dtu_sensor"].get("result") != "PASS":
        return "dtu -> sensor"
    return "none"


def _summarize_client_server(payload: Dict[str, Any]) -> Dict[str, Any]:
    if payload.get("result") == "NOT_RUN":
        return payload
    queue = payload.get("queue") or {}
    request_payload = queue.get("request_payload") or {}
    return {
        "result": payload.get("result"),
        "queue_ok": queue.get("ok"),
        "status_code": queue.get("status_code"),
        "reference": request_payload.get("reference"),
        "data_hex": request_payload.get("data"),
        "fport": request_payload.get("fPort"),
    }


def _summarize_gateway_dtu(payload: Dict[str, Any]) -> Dict[str, Any]:
    if payload.get("result") == "NOT_RUN":
        return payload
    ack = payload.get("ack") or {}
    queue = payload.get("queue") or {}
    request_payload = queue.get("request_payload") or {}
    ack_payload = ack.get("payload") or {}
    return {
        "result": payload.get("result"),
        "queue_ok": queue.get("ok"),
        "ack_ok": ack.get("ok"),
        "acknowledged": ack.get("acknowledged"),
        "reference": payload.get("reference") or request_payload.get("reference") or ack_payload.get("reference"),
        "ack_topic": payload.get("ack_topic"),
    }


def _summarize_dtu_sensor(payload: Dict[str, Any]) -> Dict[str, Any]:
    if payload.get("result") == "NOT_RUN":
        return payload
    uplink = payload.get("uplink") or {}
    matched = uplink.get("matched") or {}
    return {
        "result": payload.get("result"),
        "mode": payload.get("mode"),
        "matcher": payload.get("matcher"),
        "reference": payload.get("reference"),
        "uplink_ok": uplink.get("ok"),
        "matched_hex": matched.get("hex"),
        "matched_insert_time": matched.get("insert_time"),
    }


def _build_output(
    *,
    success: bool,
    selected: List[str],
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
        "selected_segments": selected,
        "target": results.get(selected[0], {}).get("target") if selected else None,
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

    output["client_server"] = _summarize_client_server(results["client_server"])
    output["gateway_dtu"] = _summarize_gateway_dtu(results["gateway_dtu"])
    output["dtu_sensor"] = _summarize_dtu_sensor(results["dtu_sensor"])
    return output


def _choose_shared_reference(ctx: SegmentContext) -> str:
    return (
        ctx.gateway_reference
        or ctx.sensor_reference
        or ctx.client_reference
        or build_reference("connectivity-test")
    )


def main() -> int:
    args = _parse_args()
    ctx = _build_context(args)
    shared_auth_result = authenticate(ctx.base_url, ctx.account, ctx.password, ctx.auth_timeout)
    checks = {
        "client_server": ClientServerCheck(
            base_url=ctx.base_url,
            account=ctx.account,
            password=ctx.password,
            device_id=ctx.device_id,
            data_hex=ctx.request_data_hex,
            fport=ctx.request_fport,
            reference=ctx.client_reference,
            auth_timeout=ctx.auth_timeout,
            queue_timeout=ctx.queue_timeout,
            shared_auth_result=shared_auth_result,
        ),
        "gateway_dtu": GatewayDtuCheck(
            base_url=ctx.base_url,
            account=ctx.account,
            password=ctx.password,
            device_id=ctx.device_id,
            application_id=ctx.application_id,
            data_hex=ctx.request_data_hex,
            fport=ctx.request_fport,
            reference=ctx.gateway_reference,
            auth_timeout=ctx.auth_timeout,
            queue_timeout=ctx.queue_timeout,
            ack_timeout=ctx.ack_timeout,
            mqtt_host=ctx.mqtt_host,
            mqtt_port=ctx.mqtt_port,
            mqtt_username=ctx.mqtt_username,
            mqtt_password=ctx.mqtt_password,
            mqtt_client_id=ctx.mqtt_client_id,
            mqtt_keepalive=ctx.mqtt_keepalive,
            mqtt_tls=ctx.mqtt_tls,
            shared_auth_result=shared_auth_result,
        ),
        "dtu_sensor": DtuSensorCheck(
            base_url=ctx.base_url,
            account=ctx.account,
            password=ctx.password,
            device_id=ctx.device_id,
            data_hex=ctx.request_data_hex,
            fport=ctx.request_fport,
            reference=ctx.sensor_reference,
            auth_timeout=ctx.auth_timeout,
            queue_timeout=ctx.queue_timeout,
            uplink_timeout=ctx.uplink_timeout,
            poll_interval=ctx.poll_interval,
            uplink_page_size=ctx.uplink_page_size,
            shared_auth_result=shared_auth_result,
        ),
    }
    selected = _selected_segments(args)
    results: Dict[str, Dict[str, Any]] = {
        "client_server": _not_run("Skipped by selection"),
        "gateway_dtu": _not_run("Skipped by selection"),
        "dtu_sensor": _not_run("Skipped by selection"),
    }

    if shared_auth_result.get("ok") and ctx.request_data_hex:
        shared_reference = _choose_shared_reference(ctx)
        prepared_gateway = None
        prepared_sensor = None

        if "gateway_dtu" in selected:
            prepared_gateway = checks["gateway_dtu"].prepare_ack_monitor(
                auth_result=shared_auth_result,
                reference=shared_reference,
            )
            if not prepared_gateway.get("ok"):
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
                started = False
                for downstream in selected:
                    if downstream == "gateway_dtu":
                        started = True
                        continue
                    if started:
                        results[downstream] = _not_run("Skipped because server/platform -> gateway -> dtu failed")
                output = _build_output(
                    success=False,
                    selected=selected,
                    inferred=FAULT_LABELS["gateway_dtu"],
                    failed_segment=FAULT_LABELS["gateway_dtu"],
                    ctx=ctx,
                    shared_auth_result=shared_auth_result,
                    results=results,
                    verbose=args.verbose,
                )
                print(json.dumps(output, indent=2))
                return 1

        if "dtu_sensor" in selected:
            prepared_sensor = checks["dtu_sensor"].capture_baseline(
                auth_result=shared_auth_result,
                reference=shared_reference,
            )

        trigger_start_ts = time.time()
        shared_queue_result = queue_downlink(
            ctx.base_url,
            ctx.device_id,
            shared_auth_result["token"],
            ctx.request_data_hex,
            ctx.request_fport,
            shared_reference,
            ctx.queue_timeout,
        )

        for name in selected:
            if name == "client_server":
                payload = checks["client_server"].build_result(
                    shared_auth_result,
                    shared_queue_result,
                    shared_reference,
                )
            elif name == "gateway_dtu":
                payload = checks["gateway_dtu"].finalize_with_queue(
                    prepared_gateway,
                    shared_queue_result,
                )
            else:
                payload = checks["dtu_sensor"].finalize_with_queue(
                    prepared_sensor,
                    shared_queue_result,
                    trigger_start_ts,
                )

            results[name] = payload
            if payload.get("result") != "PASS":
                if name == "client_server" and prepared_gateway and prepared_gateway.get("listener") is not None:
                    prepared_gateway["listener"].stop()
                started = False
                for downstream in selected:
                    if downstream == name:
                        started = True
                        continue
                    if started:
                        results[downstream] = _not_run(f"Skipped because {FAULT_LABELS[name]} failed")
                output = _build_output(
                    success=False,
                    selected=selected,
                    inferred=FAULT_LABELS[name],
                    failed_segment=FAULT_LABELS[name],
                    ctx=ctx,
                    shared_auth_result=shared_auth_result,
                    results=results,
                    verbose=args.verbose,
                )
                print(json.dumps(output, indent=2))
                return 1

        inferred = _infer_fault_location(results)
        output = _build_output(
            success=True,
            selected=selected,
            inferred=inferred,
            failed_segment=None,
            ctx=ctx,
            shared_auth_result=shared_auth_result,
            results=results,
            verbose=args.verbose,
        )
        print(json.dumps(output, indent=2))
        return 0

    for name in selected:
        payload = checks[name].run()
        results[name] = payload
        if payload.get("result") != "PASS":
            # Short-circuit downstream work once a segment fails.
            started = False
            for downstream in selected:
                if downstream == name:
                    started = True
                    continue
                if started:
                    results[downstream] = _not_run(f"Skipped because {FAULT_LABELS[name]} failed")
            output = _build_output(
                success=False,
                selected=selected,
                inferred=FAULT_LABELS[name],
                failed_segment=FAULT_LABELS[name],
                ctx=ctx,
                shared_auth_result=shared_auth_result,
                results=results,
                verbose=args.verbose,
            )
            print(json.dumps(output, indent=2))
            return 1

    inferred = _infer_fault_location(results)
    success = all(results[name].get("result") == "PASS" for name in selected)
    output = _build_output(
        success=success,
        selected=selected,
        inferred=inferred,
        failed_segment=None if success else inferred,
        ctx=ctx,
        shared_auth_result=shared_auth_result,
        results=results,
        verbose=args.verbose,
    )
    print(json.dumps(output, indent=2))
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
