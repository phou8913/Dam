"""Performance test that only imports communicator."""

import argparse
import contextlib
import json
import os
import sys
import time
from typing import Any
import io

import requests

WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

import communicator


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure end-to-end communicator request performance")
    parser.add_argument("--mode", default="auto", choices=["auto", "fake", "real"])
    parser.add_argument("--sensor", default="ht", choices=["ht", "ta", "wl", "mmwave"])
    parser.add_argument("--device-id", default="8695311000942380")
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--timeout-sec", type=float, default=30.0)
    parser.add_argument("--poll-interval-sec", type=float, default=0.01)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def _fake_server_is_up() -> bool:
    try:
        response = requests.get("http://127.0.0.1:5000/health", timeout=1.0)
        return response.ok
    except requests.RequestException:
        return False


def _resolve_mode(requested_mode: str) -> str:
    if requested_mode != "auto":
        return requested_mode
    return "fake" if _fake_server_is_up() else "real"


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


def _stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {
            "mean_ms": None,
            "median_ms": None,
            "p95_ms": None,
            "min_ms": None,
            "max_ms": None,
        }
    return {
        "mean_ms": _average(values),
        "median_ms": _median(values),
        "p95_ms": _p95(values),
        "min_ms": round(min(values), 2),
        "max_ms": round(max(values), 2),
    }


def _failure_breakdown(rounds: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in rounds:
        if item.get("ok"):
            continue
        stage = item.get("error_stage") or "unknown"
        counts[stage] = counts.get(stage, 0) + 1
    return counts


def _wait_for_fresh_result(
    device_id: str,
    sensor: str,
    started_at: float,
    timeout_sec: float,
    poll_interval_sec: float,
) -> dict[str, Any] | None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        result = communicator.get_buffer_data(device_id, sensor)
        if result and result.get("timestamp", 0) > started_at:
            return result
        time.sleep(poll_interval_sec)
    return None


def _run_one_round(
    device_id: str,
    sensor: str,
    timeout_sec: float,
    poll_interval_sec: float,
    quiet: bool,
) -> dict[str, Any]:
    started = time.time()
    if quiet:
        with contextlib.redirect_stdout(io.StringIO()):
            communicator.enqueue_request(device_id, sensor)
            result = _wait_for_fresh_result(device_id, sensor, started, timeout_sec, poll_interval_sec)
    else:
        communicator.enqueue_request(device_id, sensor)
        result = _wait_for_fresh_result(device_id, sensor, started, timeout_sec, poll_interval_sec)
    elapsed_ms = round((time.time() - started) * 1000, 2)

    if result is None:
        return {
            "ok": False,
            "elapsed_ms": elapsed_ms,
            "error_stage": "timeout",
            "error": "Timed out waiting for communicator buffer update",
        }

    return {
        "ok": bool(result.get("ok")),
        "elapsed_ms": elapsed_ms,
        "error_stage": result.get("error_stage"),
        "error": result.get("error"),
        "result": result,
    }


def main() -> int:
    args = _parse_args()
    selected_mode = _resolve_mode(args.mode)
    communicator.configure_backend(selected_mode)

    rounds: list[dict[str, Any]] = []
    elapsed_values: list[float] = []
    bench_started = time.time()

    for index in range(1, args.rounds + 1):
        round_result = _run_one_round(
            device_id=args.device_id,
            sensor=args.sensor,
            timeout_sec=args.timeout_sec,
            poll_interval_sec=args.poll_interval_sec,
            quiet=not args.verbose,
        )
        rounds.append(round_result)
        elapsed_values.append(round_result["elapsed_ms"])

        if args.verbose:
            print(f"Round {index}:")
            print(json.dumps(round_result, indent=2))

    total_elapsed_sec = max(time.time() - bench_started, 0.0001)
    passed = sum(1 for item in rounds if item.get("ok"))
    failed = args.rounds - passed

    summary = {
        "mode": selected_mode,
        "mode_requested": args.mode,
        "sensor": args.sensor,
        "device_id": args.device_id,
        "rounds": args.rounds,
        "passed": passed,
        "failed": failed,
        "failure_breakdown": _failure_breakdown(rounds),
        "success_rate": f"{round((passed / args.rounds) * 100, 2)}%" if args.rounds else "0%",
        "latency_ms": _stats(elapsed_values),
        "throughput_rps": round(args.rounds / total_elapsed_sec, 2),
        "notes": "Measures time from communicator.enqueue_request() to fresh buffer result.",
    }

    print(json.dumps(summary, indent=2))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
