"""DTU -> sensor connectivity check."""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable

WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from humidity_temp_sensor import HumidityTempSensor
from mmwave_sensor import MMWaveSensor
from tilt_acc_sensor import HWT901BSensor
from water_level_sensor import WaterLevelSensor

try:
    from .connectivity_common import (
        authenticate,
        build_reference,
        classify_target,
        pull_latest_uplinks,
        queue_downlink,
    )
except ImportError:
    from connectivity_common import (
        authenticate,
        build_reference,
        classify_target,
        pull_latest_uplinks,
        queue_downlink,
    )


def _latest_seen_ts(uplink_result: dict[str, Any]) -> float:
    if not uplink_result.get("ok"):
        return time.time()
    uplinks = uplink_result.get("uplinks") or []
    if not uplinks:
        return time.time()
    return max(uplink.get("ts", 0.0) for uplink in uplinks)


def _summarize_uplink(uplink: dict[str, Any] | None) -> dict[str, Any] | None:
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


def _summarize_uplink_result(uplink_result: dict[str, Any]) -> dict[str, Any]:
    uplinks = uplink_result.get("uplinks") or []
    latest = uplinks[0] if uplinks else None
    return {
        "ok": uplink_result.get("ok", False),
        "status_code": uplink_result.get("status_code"),
        "elapsed_ms": uplink_result.get("elapsed_ms"),
        "latest": _summarize_uplink(latest),
        "count": len(uplinks),
    }


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

    def _auth_result(self) -> dict[str, Any]:
        return self.shared_auth_result or authenticate(
            self.base_url,
            self.account,
            self.password,
            self.auth_timeout,
        )

    def capture_baseline(self, auth_result: dict[str, Any] | None = None, reference: str | None = None) -> dict[str, Any]:
        auth_result = auth_result or self._auth_result()
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
            "baseline_summary": _summarize_uplink_result(baseline_result),
        }

    def finalize_with_queue(
        self,
        prepared: dict[str, Any],
        queue_result: dict[str, Any] | None,
        trigger_start_ts: float | None,
    ) -> dict[str, Any]:
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
        last_uplink_summary = _summarize_uplink_result(last_uplink_result)
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
                "matched": _summarize_uplink(matched_uplink),
                "last_poll": last_uplink_summary,
            },
        }

    def run(self) -> dict[str, Any]:
        auth_result = self._auth_result()
        if not auth_result["ok"]:
            return {
                "result": "FAIL",
                "stage": "dtu_sensor",
                "target": classify_target(self.base_url),
                "base_url": self.base_url,
                "device_id": self.device_id,
                "auth": auth_result,
            }

        prepared = self.capture_baseline(auth_result=auth_result)
        trigger_start_ts = None
        queue_result = None

        if self.data_hex:
            trigger_start_ts = time.time()
            queue_result = queue_downlink(
                self.base_url,
                self.device_id,
                auth_result["token"],
                self.data_hex,
                self.fport,
                prepared["reference"],
                self.queue_timeout,
            )

        return self.finalize_with_queue(prepared, queue_result, trigger_start_ts)
