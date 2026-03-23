"""DTU -> sensor connectivity check."""

from __future__ import annotations

import base64
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

TEST_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE_ROOT = os.path.dirname(TEST_ROOT)
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from humidity_temp_sensor import HumidityTempSensor
from mmwave_sensor import MMWaveSensor
from tilt_acc_sensor import HWT901BSensor
from water_level_sensor import WaterLevelSensor

from tools.common_check import (
    build_reference,
    classify_target,
    result_payload,
)


# Parse the uplink timestamp into a comparable float value.
def _parse_insert_time(ts_str: str | None) -> float:
    if not ts_str:
        return time.time()

    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
    except Exception:
        return time.time()


# Pull recent uplinks and normalize the fields used by this check.
def pull_latest_uplinks(
    base_url: str,
    device_id: str,
    token: str,
    size: int = 10,
    timeout: float = 10.0,
) -> dict[str, Any]:
    import requests

    url = f"{base_url}/v1/uplink-storage/devices/{device_id}/uplink"
    headers = {"token": token}
    params = {"size": size, "page": 1}

    started = time.time()
    try:
        response = requests.get(url, headers=headers, params=params, timeout=timeout)
        elapsed_ms = round((time.time() - started) * 1000, 2)
    except requests.RequestException as exc:
        return result_payload(
            False,
            "uplink",
            error_type="NETWORK_FAIL",
            error_message=str(exc),
            url=url,
            params=params,
        )

    try:
        body = response.json()
    except ValueError:
        body = None

    if not response.ok:
        return result_payload(
            False,
            "uplink",
            error_type="HTTP_FAIL",
            error_message="Failed to query uplinks",
            url=url,
            status_code=response.status_code,
            elapsed_ms=elapsed_ms,
            params=params,
            response_body=body if body is not None else response.text,
        )

    uplinks_raw = body.get("result", []) if isinstance(body, dict) else []
    parsed_uplinks: list[dict[str, Any]] = []

    for uplink in uplinks_raw:
        raw_b64 = uplink.get("data")
        fport = uplink.get("fPort", 0)
        ts_str = uplink.get("insertTime")
        ts = _parse_insert_time(ts_str)
        decoded_hex = None

        if raw_b64:
            try:
                decoded_hex = base64.b64decode(raw_b64).hex()
            except Exception:
                decoded_hex = None

        parsed_uplinks.append(
            {
                "ts": ts,
                "fport": fport,
                "hex": decoded_hex,
                "raw": uplink,
            }
        )

    return result_payload(
        True,
        "uplink",
        url=url,
        status_code=response.status_code,
        elapsed_ms=elapsed_ms,
        params=params,
        uplinks=parsed_uplinks,
    )


# Small helpers for baseline tracking and compact result formatting.
def _latest_seen_ts(uplink_result: dict[str, Any]) -> float:
    if not uplink_result.get("ok"):
        return time.time()
    uplinks = uplink_result.get("uplinks") or []
    if not uplinks:
        return time.time()
    return max(uplink.get("ts", 0.0) for uplink in uplinks)


    # Summarize one uplink record.
def _summarize_one_uplink(uplink: dict[str, Any] | None) -> dict[str, Any] | None:
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


    # Summarize one uplink query result, including the latest uplink.
def _summarize_uplink_query(uplink_result: dict[str, Any]) -> dict[str, Any]:
    uplinks = uplink_result.get("uplinks") or []
    latest = uplinks[0] if uplinks else None
    return {
        "ok": uplink_result.get("ok", False),
        "status_code": uplink_result.get("status_code"),
        "elapsed_ms": uplink_result.get("elapsed_ms"),
        "latest": _summarize_one_uplink(latest),
        "count": len(uplinks),
    }


# Pick the uplink-matching rule based on the command being tested.
def _build_matcher(data_hex: str, mode: str) -> tuple[str, Callable[[dict[str, Any]], bool]]:
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


@dataclass
class DtuSensorCheck:
    base_url: str
    account: str
    password: str
    device_id: str
    data_hex: str = ""
    fport: int = 1
    reference: str = ""
    auth_timeout: float = 5.0
    queue_timeout: float = 10.0
    uplink_timeout: float = 30.0
    poll_interval: float = 1.0
    uplink_page_size: int = 20
    shared_auth_result: dict[str, Any] | None = None

    def prepare_uplink_check(self, auth_result: dict[str, Any], reference: str | None = None) -> dict[str, Any]:
        # Capture the current uplink state before the shared request is sent.
        baseline_result = pull_latest_uplinks(
            self.base_url,
            self.device_id,
            auth_result["token"],
            size=self.uplink_page_size,
            timeout=self.queue_timeout,
        )
        return {
            "auth_result": auth_result,
            "reference": reference or self.reference or build_reference("dtu-sensor-test"),
            "baseline_result": baseline_result,
            "baseline_ts": _latest_seen_ts(baseline_result),
            "baseline_summary": _summarize_uplink_query(baseline_result),
        }

    def finalize_with_queue(
        self,
        prepared: dict[str, Any],
        queue_result: dict[str, Any] | None,
        trigger_start_ts: float | None,
    ) -> dict[str, Any]:
        # Wait for a fresh uplink that matches the expected sensor response.
        auth_result = prepared["auth_result"]
        baseline_summary = prepared["baseline_summary"]
        baseline_result = prepared["baseline_result"]
        baseline_ts = prepared["baseline_ts"]
        reference = prepared["reference"]
        mode = "trigger" if self.data_hex else "passive"
        matcher_name, matcher = _build_matcher(self.data_hex, mode)

        if self.data_hex and queue_result is not None and not queue_result["ok"]:
            return {
                "result": "FAIL",
                "stage": "dtu_sensor",
                "target": classify_target(self.base_url),
                "base_url": self.base_url,
                "device_id": self.device_id,
                "reference": reference,
                "auth": {
                    "ok": True,
                    "status_code": auth_result.get("status_code"),
                    "elapsed_ms": auth_result.get("elapsed_ms"),
                },
                "baseline_uplink": baseline_summary,
                "queue": queue_result,
            }

        wait_start_ts = trigger_start_ts if trigger_start_ts is not None else time.time()
        deadline = wait_start_ts + self.uplink_timeout
        matched_uplink = None
        last_uplink_result = baseline_result
        freshness_cutoff = max(baseline_ts, trigger_start_ts if trigger_start_ts is not None else wait_start_ts)

        while time.time() < deadline:
            last_uplink_result = pull_latest_uplinks(
                self.base_url,
                self.device_id,
                auth_result["token"],
                size=self.uplink_page_size,
                timeout=self.queue_timeout,
            )
            if last_uplink_result.get("ok"):
                for uplink in last_uplink_result.get("uplinks") or []:
                    if uplink.get("ts", 0.0) > freshness_cutoff and matcher(uplink):
                        matched_uplink = uplink
                        break
            if matched_uplink is not None:
                break
            time.sleep(self.poll_interval)

        success = matched_uplink is not None
        last_uplink_summary = _summarize_uplink_query(last_uplink_result)
        return {
            "result": "PASS" if success else "FAIL",
            "stage": "dtu_sensor",
            "target": classify_target(self.base_url),
            "mode": mode,
            "matcher": matcher_name,
            "base_url": self.base_url,
            "device_id": self.device_id,
            "reference": reference if self.data_hex else None,
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
                "matched": _summarize_one_uplink(matched_uplink),
                "last_poll": last_uplink_summary,
            },
        }

    @staticmethod
    def summarize(payload: dict[str, Any]) -> dict[str, Any]:
        # Keep only the fields that matter in the final end-to-end summary.
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
