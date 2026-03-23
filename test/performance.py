"""Simple performance runner for the end-to-end connectivity test."""

import argparse
import json
import time
from typing import Any

from connectivity import (
    DEFAULT_ACCOUNT,
    DEFAULT_APPLICATION_ID,
    DEFAULT_DEVICE_ID,
    DEFAULT_MQTT_CLIENT_ID,
    DEFAULT_MQTT_HOST,
    DEFAULT_MQTT_KEEPALIVE,
    DEFAULT_MQTT_PASSWORD,
    DEFAULT_MQTT_PORT,
    DEFAULT_MQTT_USERNAME,
    DEFAULT_PASSWORD,
    SegmentContext,
    run_end_to_end,
)
from tools.common_check import choose_base_url


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the end-to-end test multiple times and print simple stats")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--base-url", default=choose_base_url())
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
    parser.add_argument("--mqtt-host", default=DEFAULT_MQTT_HOST)
    parser.add_argument("--mqtt-port", type=int, default=int(DEFAULT_MQTT_PORT))
    parser.add_argument("--mqtt-username", default=DEFAULT_MQTT_USERNAME)
    parser.add_argument("--mqtt-password", default=DEFAULT_MQTT_PASSWORD)
    parser.add_argument("--mqtt-client-id", default=DEFAULT_MQTT_CLIENT_ID)
    parser.add_argument("--mqtt-keepalive", type=int, default=int(DEFAULT_MQTT_KEEPALIVE))
    parser.add_argument("--mqtt-tls", action="store_true")
    parser.add_argument("--verbose", action="store_true", help="Print each run result")
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
        reference="",
        mqtt_host=args.mqtt_host,
        mqtt_port=args.mqtt_port,
        mqtt_username=args.mqtt_username,
        mqtt_password=args.mqtt_password,
        mqtt_client_id=args.mqtt_client_id,
        mqtt_keepalive=args.mqtt_keepalive,
        mqtt_tls=args.mqtt_tls,
    )


def _get_ms(result: dict, *path: str) -> float | None:
    current = result
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    if isinstance(current, (int, float)):
        return float(current)
    return None


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return round(ordered[middle], 2)
    return round((ordered[middle - 1] + ordered[middle]) / 2, 2)


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95) - 1))
    return round(ordered[index], 2)


def _stats(values: list[float | None]) -> dict[str, float | None]:
    numbers = [value for value in values if value is not None]
    if not numbers:
        return {
            "mean_ms": None,
            "median_ms": None,
            "p95_ms": None,
            "min_ms": None,
            "max_ms": None,
        }
    return {
        "mean_ms": _average(numbers),
        "median_ms": _median(numbers),
        "p95_ms": _p95(numbers),
        "min_ms": round(min(numbers), 2),
        "max_ms": round(max(numbers), 2),
    }


def main() -> int:
    args = _parse_args()
    ctx = _build_context(args)
    runs: list[dict[str, Any]] = []
    total_times: list[float] = []

    for index in range(1, args.runs + 1):
        started = time.time()
        result = run_end_to_end(ctx, verbose=True)
        total_times.append(round((time.time() - started) * 1000, 2))
        runs.append(result)
        if args.verbose:
            print(f"Run {index}:")
            print(json.dumps(result, indent=2))

    passed = sum(1 for run in runs if run.get("result") == "PASS")
    auth_times = [_get_ms(run, "auth", "elapsed_ms") for run in runs]
    queue_times = [_get_ms(run, "client_server", "queue", "elapsed_ms") for run in runs]
    ack_times = [_get_ms(run, "gateway_dtu", "ack", "elapsed_ms") for run in runs]
    uplink_poll_times = [_get_ms(run, "dtu_sensor", "uplink", "last_poll", "elapsed_ms") for run in runs]

    summary = {
        "runs": args.runs,
        "base_url": args.base_url,
        "passed": passed,
        "failed": args.runs - passed,
        "success_rate": f"{round((passed / args.runs) * 100, 2)}%" if args.runs else "0%",
        "total_ms": _stats(total_times),
        "auth_ms": _stats(auth_times),
        "queue_ms": _stats(queue_times),
        "ack_ms": _stats(ack_times),
        "last_uplink_poll_ms": _stats(uplink_poll_times),
        "notes": "Use --verbose if you want to see every run result.",
    }

    print(json.dumps(summary, indent=2))
    return 0 if passed == args.runs else 1


if __name__ == "__main__":
    raise SystemExit(main())
