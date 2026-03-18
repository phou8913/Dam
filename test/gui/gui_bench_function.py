"""
Self-contained functional checks for the Tkinter dashboard.

This script mirrors the style of gateway_relay/test/dummy_bench_function.py:
- no real backend required
- uses a fake communicator
- prints PASS / FAIL style results

Usage:
    python test/gui_bench_function.py
"""

from __future__ import annotations

import sys
import tkinter as tk
from contextlib import contextmanager
from pathlib import Path

# 1. Put the project root on sys.path so this test can import gui.py from /test.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import gui


SEP = "=" * 68


# 2. Define a fake communicator so GUI behavior can be tested without real I/O.
class FakeCommunicator:
    def __init__(self) -> None:
        self.enqueue_calls: list[tuple[str, str]] = []
        self.buffer: dict[tuple[str, str], dict] = {}
        self.configured_mode: str | None = None

    def configure_backend(self, mode: str = "real") -> None:
        self.configured_mode = mode

    def enqueue_request(self, dev_eui: str, sensor: str) -> None:
        self.enqueue_calls.append((dev_eui, sensor))

    def get_buffer_data(self, dev_eui: str, sensor: str):
        return self.buffer.get((dev_eui, sensor))


# 3. Temporarily replace gui.py's communicator hooks with the fake test double.
@contextmanager
def patched_communicator(fake: FakeCommunicator):
    # Swap out the real communicator hooks so the dashboard can be exercised
    # without threads, HTTP calls, or the fake server process.
    old_enqueue = gui.communicator.enqueue_request
    old_get_buffer = gui.communicator.get_buffer_data
    old_configure = gui.communicator.configure_backend
    gui.communicator.enqueue_request = fake.enqueue_request
    gui.communicator.get_buffer_data = fake.get_buffer_data
    gui.communicator.configure_backend = fake.configure_backend
    try:
        yield
    finally:
        gui.communicator.enqueue_request = old_enqueue
        gui.communicator.get_buffer_data = old_get_buffer
        gui.communicator.configure_backend = old_configure


def section(title: str) -> None:
    print(f"\n{SEP}\n  {title}\n{SEP}")


def check(label: str, cond: bool, details: str = "") -> bool:
    if cond:
        print(f"  PASS  {label}")
        return True
    print(f"  FAIL  {label}: {details or 'condition was False'}")
    return False


# 4. Build the dashboard in a hidden Tk root and intercept scheduled callbacks.
def make_dashboard():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise RuntimeError(
            "Tkinter could not start. Install/use a Python build with Tcl/Tk "
            "support before running GUI tests."
        ) from exc
    root.withdraw()
    scheduled: list[tuple[int, object]] = []

    def fake_after(ms: int, callback=None):
        # Capture scheduled refreshes instead of entering the real Tk timer loop.
        scheduled.append((ms, callback))
        return f"after-{len(scheduled)}"

    root.after = fake_after  # type: ignore[assignment]
    dashboard = gui.SensorDashboard(root)
    return root, dashboard, scheduled


# 5. Run the functional checks in sequence and verify visible GUI behavior.
def main() -> int:
    fake = FakeCommunicator()

    with patched_communicator(fake):
        try:
            root, dashboard, scheduled = make_dashboard()
        except RuntimeError as exc:
            section("Environment check")
            print(f"  SKIP  {exc}")
            return 2
        failures = 0

        try:
            section("GUI functional checks")

            # Verify the widget-level helper trims user input before forwarding.
            dashboard.ht_eui_entry.delete(0, tk.END)
            dashboard.ht_eui_entry.insert(0, "  8695311000942380  ")
            dashboard.enqueue_request("ht", dashboard.ht_eui_entry)
            if not check(
                "enqueue_request trims device EUI",
                fake.enqueue_calls[-1] == ("8695311000942380", "ht"),
                f"calls={fake.enqueue_calls}",
            ):
                failures += 1

            # Auto mode should flip UI state and immediately queue the first read.
            before_toggle_calls = len(fake.enqueue_calls)
            dashboard.toggle_auto("ht", dashboard.ht_eui_entry, dashboard.ht_auto_button)
            auto_started = (
                dashboard.auto_enabled["ht"]
                and dashboard.ht_auto_button.cget("text") == "Stop Auto"
                and len(fake.enqueue_calls) == before_toggle_calls + 1
            )
            if not check(
                "toggle_auto starts auto mode and enqueues immediately",
                auto_started,
                f"enabled={dashboard.auto_enabled['ht']} text={dashboard.ht_auto_button.cget('text')}",
            ):
                failures += 1

            # Stopping auto mode should restore the idle button label.
            dashboard.toggle_auto("ht", dashboard.ht_eui_entry, dashboard.ht_auto_button)
            if not check(
                "toggle_auto stops auto mode",
                (not dashboard.auto_enabled["ht"]) and dashboard.ht_auto_button.cget("text") == "Start Auto",
                f"enabled={dashboard.auto_enabled['ht']} text={dashboard.ht_auto_button.cget('text')}",
            ):
                failures += 1

            # Seed the fake buffer with decoded sensor payloads, mirroring the
            # shape communicator.py stores after successful reads.
            fake.buffer[(gui.HUMIDITY_TEMP_EUI, "ht")] = {
                "ok": True,
                "data": {
                    "temperature_c": 23.45,
                    "humidity_rh": 56.78,
                    "dewpoint_c": 14.32,
                    "crc_valid": True,
                    "raw_hex": "0104060929152E0598ABCD",
                },
            }
            fake.buffer[(gui.TILT_ACC_EUI, "ta")] = {
                "ok": True,
                "data": {
                    "roll": 1.25,
                    "pitch": -2.5,
                    "yaw": 15.75,
                    "ax_g": 0.101,
                    "ay_g": -0.202,
                    "az_g": 0.999,
                    "raw_hex": "5003060123ABCD",
                },
            }
            fake.buffer[(gui.WATER_LEVEL_EUI, "wl")] = {
                "ok": True,
                "data": {
                    "level_m": 0.321,
                    "crc_valid": True,
                    "raw_hex": "7B03043EA45A1D",
                },
            }
            fake.buffer[(gui.MMWAVE_EUI, "mmwave")] = {
                "ok": True,
                "data": {
                    "targets": {
                        "target1": [12.5, 2.4],
                        "target2": [-30.0, 1.1],
                    },
                },
            }

            # One refresh pass should pull all buffered results into the widgets.
            dashboard.refresh_ui()

            if not check(
                "humidity panel refreshes from buffer",
                dashboard.ht_temp.cget("text") == "23.45 °C"
                and dashboard.ht_humidity.cget("text") == "56.78 %RH"
                and dashboard.ht_dewpoint.cget("text") == "14.32 °C",
                (
                    f"temp={dashboard.ht_temp.cget('text')} "
                    f"humidity={dashboard.ht_humidity.cget('text')} "
                    f"dew={dashboard.ht_dewpoint.cget('text')}"
                ),
            ):
                failures += 1

            if not check(
                "tilt panel refreshes from buffer",
                dashboard.ta_roll.cget("text") == "1.25°"
                and dashboard.ta_pitch.cget("text") == "-2.50°"
                and dashboard.ta_az.cget("text") == "0.999g",
                (
                    f"roll={dashboard.ta_roll.cget('text')} "
                    f"pitch={dashboard.ta_pitch.cget('text')} "
                    f"az={dashboard.ta_az.cget('text')}"
                ),
            ):
                failures += 1

            if not check(
                "water level panel refreshes from buffer",
                dashboard.wl_level.cget("text") == "0.321 m"
                and dashboard.wl_crc.cget("text") == "True",
                f"level={dashboard.wl_level.cget('text')} crc={dashboard.wl_crc.cget('text')}",
            ):
                failures += 1

            if not check(
                "mmwave target list refreshes from buffer",
                dashboard.target_labels[0].cget("text") == "Target 1: 12.5° @ 2.40m"
                and dashboard.target_labels[1].cget("text") == "Target 2: -30.0° @ 1.10m",
                (
                    f"t1={dashboard.target_labels[0].cget('text')} "
                    f"t2={dashboard.target_labels[1].cget('text')}"
                ),
            ):
                failures += 1

            if not check(
                "dashboard schedules periodic refresh",
                len(scheduled) >= 2,
                f"scheduled_calls={len(scheduled)}",
            ):
                failures += 1

            section("Results")
            total = 8
            passed = total - failures
            print(f"  {passed}/{total} checks passed")
            if failures:
                print("  FAILURES detected")
                return 1
            print("  All GUI functional checks passed.")
            return 0
        finally:
            root.destroy()


# 6. Expose the script as a direct CLI entry point, just like the relay demos.
if __name__ == "__main__":
    raise SystemExit(main())
