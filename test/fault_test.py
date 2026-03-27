import os
import subprocess
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import communicator


DEVICE_ID = "8695311000942380"
SENSOR = "ht"
SERVER_URL = "http://127.0.0.1:5000/health"

CASES = [
    {"env": {"FAKE_AUTH_OK": "0"}},
    {"env": {"FAKE_QUEUE_OK": "0"}},
    {"env": {"FAKE_ACK_ENABLED": "0"}},
    {"env": {"FAKE_UPLINK_ENABLED": "0"}},
    {"env": {"FAKE_ACKNOWLEDGED": "0"}},
    {"env": {}},
]


def _start_fake_server(extra_env: dict[str, str]) -> subprocess.Popen:
    env = os.environ.copy()
    env.update(extra_env)
    return subprocess.Popen(
        [sys.executable, "fake_server.py"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_for_server(timeout_sec: float = 5.0) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            response = requests.get(SERVER_URL, timeout=0.5)
            if response.ok:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.1)
    return False


def _wait_for_result(started_at: float, timeout_sec: float = 15.0):
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        result = communicator.get_buffer_data(DEVICE_ID, SENSOR)
        if result and result.get("timestamp", 0) > started_at:
            return result
        time.sleep(0.05)
    return None


def _run_case(case: dict[str, object]) -> None:
    server = _start_fake_server(case["env"])
    try:
        if not _wait_for_server():
            return

        communicator.configure_backend("fake")
        started_at = time.time()
        communicator.enqueue_request(DEVICE_ID, SENSOR)
        result = _wait_for_result(started_at)

        if result is None:
            return
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)
        time.sleep(0.2)


def main() -> int:
    for case in CASES:
        _run_case(case)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
