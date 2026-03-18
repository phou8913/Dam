"""
Simple GUI refresh benchmark for the Tkinter dashboard.

This mirrors the style of gateway_relay/test/dummy_bench_exchange.py by
printing mean / median / p95 / min / max timings for key UI paths.

Usage:
    python test/gui_bench_refresh.py
"""

from __future__ import annotations

import statistics
import sys
import time
import tkinter as tk
from contextlib import contextmanager
from pathlib import Path

# 1. Put the project root on sys.path so this benchmark can import gui.py from /test.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import gui


SEP = "=" * 66
WARMUP = 10
BENCH_ROUNDS = 120


# 2. Define a fake communicator so refresh timing is isolated from real I/O.
class FakeCommunicator:
    def __init__(self) -> None:
        self.buffer: dict[tuple[str, str], dict] = {}

    def configure_backend(self, mode: str = "real") -> None:
        del mode

    def enqueue_request(self, dev_eui: str, sensor: str) -> None:
        del dev_eui, sensor

    def get_buffer_data(self, dev_eui: str, sensor: str):
        return self.buffer.get((dev_eui, sensor))


# 3. Temporarily replace gui.py's communicator hooks with the fake benchmark double.
@contextmanager
def patched_communicator(fake: FakeCommunicator):
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


# 4. Build the dashboard in a hidden Tk root and suppress the real timer loop.
def make_dashboard():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise RuntimeError(
            "Tkinter could not start. Install/use a Python build with Tcl/Tk "
            "support before running GUI benchmarks."
        ) from exc
    root.withdraw()

    def fake_after(ms: int, callback=None):
        del ms, callback
        return "after-bench"

    root.after = fake_after  # type: ignore[assignment]
    dashboard = gui.SensorDashboard(root)
    return root, dashboard


# 5. Run one benchmark target repeatedly and report summary timing metrics.
def run_bench(label: str, fn, rounds: int, warmup: int) -> None:
    for _ in range(warmup):
        fn()

    times = []
    for _ in range(rounds):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000.0)

    sorted_times = sorted(times)
    p95 = sorted_times[int(0.95 * len(sorted_times))]
    throughput = 1000.0 / statistics.mean(times)

    print(f"\n  {label}")
    print(f"    rounds     : {rounds}")
    print(f"    mean       : {statistics.mean(times):.2f} ms")
    print(f"    median     : {statistics.median(times):.2f} ms")
    print(f"    p95        : {p95:.2f} ms")
    print(f"    min / max  : {min(times):.2f} / {max(times):.2f} ms")
    print(f"    throughput : {throughput:.1f} req/s")


# 6. Seed benchmark data, build the dashboard, and measure key refresh paths.
def main() -> int:
    fake = FakeCommunicator()
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
                "target3": [48.0, 3.8],
            },
        },
    }

    with patched_communicator(fake):
        try:
            root, dashboard = make_dashboard()
        except RuntimeError as exc:
            print(f"\n{SEP}")
            print("  GUI refresh benchmark")
            print(f"{SEP}")
            print(f"\n  SKIP  {exc}\n")
            return 2
        try:
            print(f"\n{SEP}")
            print("  GUI refresh benchmark")
            print(f"  warmup={WARMUP}  rounds={BENCH_ROUNDS}")
            print(f"{SEP}")

            run_bench(
                "update_humidity_temp_display",
                lambda: dashboard.update_ht_display(fake.buffer[(gui.HUMIDITY_TEMP_EUI, "ht")]["data"]),
                BENCH_ROUNDS,
                WARMUP,
            )
            run_bench(
                "update_mmwave_display",
                lambda: dashboard.update_mmwave_display(fake.buffer[(gui.MMWAVE_EUI, "mmwave")]["data"]),
                BENCH_ROUNDS,
                WARMUP,
            )
            run_bench(
                "refresh_ui full pass",
                dashboard.refresh_ui,
                BENCH_ROUNDS,
                WARMUP,
            )

            print(f"\n{SEP}\n  DONE\n{SEP}\n")
            return 0
        finally:
            root.destroy()


# 7. Expose the script as a direct CLI entry point, just like the relay demos.
if __name__ == "__main__":
    raise SystemExit(main())
