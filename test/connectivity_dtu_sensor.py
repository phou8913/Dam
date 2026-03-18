"""
DTU -> sensor connectivity test using the platform uplink storage API.

Modes:
1. Passive mode: do not send any downlink, just wait for a fresh uplink.
2. Trigger mode: send a downlink first, then wait for a fresh uplink.
"""

import argparse
import json
import os
import sys
import time

WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from humidity_temp_sensor import HumidityTempSensor
from mmwave_sensor import MMWaveSensor
from tilt_acc_sensor import HWT901BSensor
from water_level_sensor import WaterLevelSensor
from connectivity_common import (
    authenticate,
    build_reference,
    choose_base_url,
    classify_target,
    pull_latest_uplinks,
    queue_downlink,
)


DEFAULT_BASE_URL = choose_base_url()
DEFAULT_ACCOUNT = os.getenv("LORA_ACCOUNT", "admin")
DEFAULT_PASSWORD = os.getenv("LORA_PASSWORD", "admin")
DEFAULT_DEVICE_ID = os.getenv("DEVICE_ID", "8695311000942380")


def _latest_seen_ts(uplink_result: dict) -> float:
    if not uplink_result.get("ok"):
        return time.time()
    uplinks = uplink_result.get("uplinks") or []
    if not uplinks:
        return time.time()
    return max(uplink.get("ts", 0.0) for uplink in uplinks)


def _summarize_uplink(uplink: dict | None) -> dict | None:
    if not uplink:
        return None
    raw = uplink.get("raw") or {}
    return {
        "ts": uplink.get("ts"),
        "insert_time": raw.get("insertTime"),
        "fport": uplink.get("fport"),
        "hex": uplink.get("hex"),
        "data": raw.get("data"),
    }


def _summarize_uplink_result(uplink_result: dict) -> dict:
    uplinks = uplink_result.get("uplinks") or []
    latest = uplinks[0] if uplinks else None
    return {
        "ok": uplink_result.get("ok", False),
        "status_code": uplink_result.get("status_code"),
        "elapsed_ms": uplink_result.get("elapsed_ms"),
        "latest": _summarize_uplink(latest),
        "count": len(uplinks),
    }


def _build_matcher(data_hex: str, mode: str):
    ht = HumidityTempSensor()
    ta = HWT901BSensor()
    wl = WaterLevelSensor()
    mmwave = MMWaveSensor()
    normalized = (data_hex or "").lower()

    if not normalized and mode == "passive":
        return "passive_any", lambda uplink: uplink.get("ts", 0.0) > 0

    if normalized == ht.encode_read_command().lower():
        return "ht", lambda uplink: bool(uplink.get("hex")) and ht.validate_response(uplink["hex"])

    if normalized == wl.encode_read_command().lower():
        return "wl", lambda uplink: bool(uplink.get("hex")) and wl.validate_response(uplink["hex"])

    if normalized == ta.encode_read_angles_command().lower():
        return "ta_angles", lambda uplink: bool(uplink.get("hex")) and ta.validate_angles_response(uplink["hex"])

    if normalized == ta.encode_read_accel_command().lower():
        return "ta_accel", lambda uplink: bool(uplink.get("hex")) and ta.validate_accel_response(uplink["hex"])

    if mode == "passive":
        return "mmwave_or_any", lambda uplink: bool(uplink.get("hex")) and mmwave.decode_targets(uplink["hex"]) is not None

    return "fresh_uplink_only", lambda uplink: True


def main() -> int:
    # Parse runtime parameters for auth, optional trigger downlink, and uplink polling.
    parser = argparse.ArgumentParser(description="Test DTU -> sensor connectivity with fresh uplinks")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--account", default=DEFAULT_ACCOUNT)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--device-id", default=DEFAULT_DEVICE_ID)
    parser.add_argument("--data-hex", default="")
    parser.add_argument("--fport", type=int, default=1)
    parser.add_argument("--reference", default="")
    parser.add_argument("--auth-timeout", type=float, default=5.0)
    parser.add_argument("--queue-timeout", type=float, default=10.0)
    parser.add_argument("--uplink-timeout", type=float, default=30.0)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--uplink-page-size", type=int, default=20)
    args = parser.parse_args()

    mode = "trigger" if args.data_hex else "passive"
    matcher_name, matcher = _build_matcher(args.data_hex, mode)

    # Authenticate first because both trigger mode and uplink queries require a token.
    auth_result = authenticate(args.base_url, args.account, args.password, args.auth_timeout)
    if not auth_result["ok"]:
        print(json.dumps({
            "result": "FAIL",
            "stage": "dtu_sensor",
            "target": classify_target(args.base_url),
            "base_url": args.base_url,
            "device_id": args.device_id,
            "auth": auth_result,
        }, indent=2))
        return 1

    # Capture the latest known uplink timestamp so we only count fresh data.
    baseline_result = pull_latest_uplinks(
        args.base_url,
        args.device_id,
        auth_result["token"],
        size=args.uplink_page_size,
        timeout=args.queue_timeout,
    )
    baseline_ts = _latest_seen_ts(baseline_result)
    baseline_summary = _summarize_uplink_result(baseline_result)

    queue_result = None
    reference = args.reference or build_reference("dtu-sensor-test")
    wait_start_ts = time.time()
    trigger_start_ts = None

    # Trigger mode sends one downlink first; passive mode just waits for the next new uplink.
    if args.data_hex:
        trigger_start_ts = time.time()
        queue_result = queue_downlink(
            args.base_url,
            args.device_id,
            auth_result["token"],
            args.data_hex,
            args.fport,
            reference,
            args.queue_timeout,
        )
        if not queue_result["ok"]:
            print(json.dumps({
                "result": "FAIL",
                "stage": "dtu_sensor",
                "target": classify_target(args.base_url),
                "base_url": args.base_url,
                "device_id": args.device_id,
                "reference": reference,
                "auth": {
                    "ok": True,
                    "status_code": auth_result.get("status_code"),
                    "elapsed_ms": auth_result.get("elapsed_ms"),
                },
                "baseline_uplink": baseline_summary,
                "queue": queue_result,
            }, indent=2))
            return 1
        wait_start_ts = trigger_start_ts

    # Poll uplink storage until a fresh uplink appears or the timeout expires.
    deadline = wait_start_ts + args.uplink_timeout
    matched_uplink = None
    last_uplink_result = baseline_result
    freshness_cutoff = max(baseline_ts, trigger_start_ts if trigger_start_ts is not None else wait_start_ts)

    while time.time() < deadline:
        last_uplink_result = pull_latest_uplinks(
            args.base_url,
            args.device_id,
            auth_result["token"],
            size=args.uplink_page_size,
            timeout=args.queue_timeout,
        )
        if last_uplink_result.get("ok"):
            for uplink in last_uplink_result.get("uplinks") or []:
                if uplink.get("ts", 0.0) > freshness_cutoff and matcher(uplink):
                    matched_uplink = uplink
                    break
        if matched_uplink is not None:
            break
        time.sleep(args.poll_interval)

    # Report PASS only when a fresh uplink is observed after the baseline/trigger point.
    success = matched_uplink is not None
    last_uplink_summary = _summarize_uplink_result(last_uplink_result)
    output = {
        "result": "PASS" if success else "FAIL",
        "stage": "dtu_sensor",
        "target": classify_target(args.base_url),
        "mode": mode,
        "matcher": matcher_name,
        "base_url": args.base_url,
        "device_id": args.device_id,
        "reference": reference if args.data_hex else None,
        "auth": {
            "ok": True,
            "status_code": auth_result.get("status_code"),
            "elapsed_ms": auth_result.get("elapsed_ms"),
        },
        "baseline_uplink": baseline_summary,
        "queue": queue_result,
        "uplink": {
            "ok": success,
            "freshness_cutoff": freshness_cutoff,
            "matched": _summarize_uplink(matched_uplink),
            "last_poll": last_uplink_summary,
        },
    }
    print(json.dumps(output, indent=2))
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
