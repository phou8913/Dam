"""Simulate one user clicking the same sensor button many times."""

import argparse
import json
import os
import sys
import time

WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

import communicator


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Queue many button clicks for one device and sensor")
    parser.add_argument("--device-id", default="8695311000942380")
    parser.add_argument("--sensor", default="ht", choices=["ht", "ta", "wl", "mmwave"])
    parser.add_argument("--clicks", type=int, default=20)
    parser.add_argument("--interval-ms", type=int, default=0)
    parser.add_argument("--base-url", default="http://127.0.0.1:5000/api")
    parser.add_argument("--wait-timeout", type=float, default=60.0)
    return parser.parse_args()


def _is_fake_url(base_url: str) -> bool:
    normalized = base_url.rstrip("/")
    return normalized in {
        "http://127.0.0.1:5000/api",
        "http://localhost:5000/api",
    }


def main() -> int:
    args = _parse_args()

    communicator.configure_backend("fake" if _is_fake_url(args.base_url) else "real")
    communicator.BASE_URL = args.base_url

    dev_eui = args.device_id.strip()
    sensor = args.sensor.strip()
    worker = communicator._get_device_worker(dev_eui)
    inflight_lock = communicator._get_inflight_lock(dev_eui)

    started = time.time()
    for _ in range(args.clicks):
        communicator.enqueue_request(dev_eui, sensor)
        if args.interval_ms > 0:
            time.sleep(args.interval_ms / 1000.0)
    enqueue_elapsed_ms = round((time.time() - started) * 1000, 2)

    peak_global_queue = communicator.request_queue.qsize()
    peak_device_queue = worker.queue.qsize()

    wait_started = time.time()
    while time.time() - wait_started < args.wait_timeout:
        global_queue_empty = communicator.request_queue.qsize() == 0
        device_queue_empty = worker.queue.qsize() == 0
        idle = not inflight_lock.locked()
        if global_queue_empty and device_queue_empty and idle:
            break
        time.sleep(0.1)

    latest_result = communicator.get_buffer_data(dev_eui, sensor)
    summary = {
        "device_id": dev_eui,
        "sensor": sensor,
        "clicks": args.clicks,
        "interval_ms": args.interval_ms,
        "base_url": args.base_url,
        "enqueue_elapsed_ms": enqueue_elapsed_ms,
        "global_queue_size_after_enqueue": peak_global_queue,
        "device_queue_size_after_enqueue": peak_device_queue,
        "waited_sec": round(time.time() - wait_started, 2),
        "global_queue_size_final": communicator.request_queue.qsize(),
        "device_queue_size_final": worker.queue.qsize(),
        "inflight_final": inflight_lock.locked(),
        "latest_result": latest_result,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
