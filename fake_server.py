"""
Fake LoRa Gateway HTTP Server
Simulates the real LoRa gateway API for testing purposes.
Mimics the same endpoints and response format as the real API.

Usage:
    python fake_server.py

Then configure communicator.py to use BASE_URL = "http://127.0.0.1:5000/api"
"""

from flask import Flask, request, jsonify
import time
import random
import threading
import os
from typing import Dict, List, Any
from collections import defaultdict
import struct


app = Flask(__name__)

# In-memory uplink history keyed by device ID.
device_uplinks: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
uplinks_lock = threading.Lock()

# Optional knobs for testing retries and timing behavior.
SIM_PACKET_LOSS_RATE = 0.0
SIM_DELAY_SEC = 0.0


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _fake_auth_ok() -> bool:
    return _env_bool("FAKE_AUTH_OK", True)


def _fake_queue_ok() -> bool:
    return _env_bool("FAKE_QUEUE_OK", True)


def _fake_uplink_enabled() -> bool:
    return _env_bool("FAKE_UPLINK_ENABLED", True)


def _fake_sensor_match() -> str:
    return os.getenv("FAKE_SENSOR_MATCH", "").strip().lower()


def generate_timestamp() -> str:
    """Generate ISO 8601 timestamp string."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def hex_to_base64(hex_str: str) -> str:
    """Convert hex string to base64."""
    import base64
    return base64.b64encode(bytes.fromhex(hex_str)).decode('ascii')


def _crc16_modbus(data: bytes) -> int:
    """Calculate Modbus RTU CRC16 checksum."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def generate_fake_humidity_temp_hex() -> str:
    """Generate fake humidity/temp sensor response hex."""
    temp_c = 18.0 + random.random() * 10.0
    hum_rh = 30.0 + random.random() * 40.0
    dew_c = temp_c - (100.0 - hum_rh) / 10.0

    t_raw = int(temp_c * 100)
    h_raw = int(hum_rh * 100)
    d_raw = int(dew_c * 100)

    payload = struct.pack(">BBBhHh", 0x01, 0x04, 0x06, t_raw, h_raw, d_raw)
    frame = payload + struct.pack("<H", _crc16_modbus(payload))
    return frame.hex()


def generate_fake_angles_hex() -> str:
    """Generate fake tilt/acc angles response hex."""
    roll = random.uniform(-10, 10)
    pitch = random.uniform(-10, 10)
    yaw = random.uniform(-10, 10)

    def to_raw(deg: float) -> int:
        return int(deg / 180.0 * 32768)

    header = bytes([0x50, 0x03, 0x06])
    data6 = struct.pack(">hhh", to_raw(roll), to_raw(pitch), to_raw(yaw))
    frame = header + data6 + b"\x00\x00"
    return frame.hex()


def generate_fake_accel_hex() -> str:
    """Generate fake tilt/acc acceleration response hex."""
    ax = random.uniform(-0.5, 0.5)
    ay = random.uniform(-0.5, 0.5)
    az = random.uniform(-0.5, 0.5)

    def to_raw(g: float) -> int:
        return int(g / 16.0 * 32768)

    header = bytes([0x50, 0x03, 0x06])
    data6 = struct.pack(">hhh", to_raw(ax), to_raw(ay), to_raw(az))
    frame = header + data6 + b"\x00\x00"
    return frame.hex()


def generate_fake_water_level_hex() -> str:
    """Generate fake water level response hex."""
    SLAVE_ADDR = 123
    level_m = random.uniform(0.05, 0.50)
    header = struct.pack(">BBB", SLAVE_ADDR, 0x03, 0x04)
    data4 = struct.pack(">f", float(level_m))
    frame_wo_crc = header + data4
    crc = _crc16_modbus(frame_wo_crc)
    frame = frame_wo_crc + struct.pack("<H", crc)
    return frame.hex()


def generate_fake_mmwave_hex(max_targets: int = 3) -> str:
    """Generate fake mmWave radar response hex."""
    n = random.randint(1, max(1, min(5, max_targets)))
    payload = b""
    for _ in range(n):
        distance_m = random.uniform(0.2, 5.0)
        distance_raw = int(distance_m * 1000)
        angle_deg = random.uniform(-60.0, 60.0)
        angle_raw = int(angle_deg * 100)
        payload += struct.pack(">Hh", distance_raw, angle_raw)
    return payload.hex()


def _sensor_response_hex_for_mode(mode: str) -> str | None:
    if mode == "ht":
        return generate_fake_humidity_temp_hex()
    if mode == "ta":
        return generate_fake_angles_hex()
    if mode == "ta_accel":
        return generate_fake_accel_hex()
    if mode == "wl":
        return generate_fake_water_level_hex()
    if mode == "mmwave":
        return generate_fake_mmwave_hex(max_targets=3)
    return None


def process_downlink(device_id: str, hex_data: str, fport: int):
    """
    Process downlink command and generate appropriate uplink response.
    Routes to correct sensor profile based on command pattern.
    """
    if not _fake_uplink_enabled():
        return

    cmd = hex_data.replace(" ", "").upper()
    forced_sensor = _fake_sensor_match()
    forced_response = _sensor_response_hex_for_mode(forced_sensor)
    if forced_response is not None:
        store_uplink(device_id, forced_response, fport)
        return
    
    # Humidity/temperature command family.
    # Accept both 0x03 and 0x04 read variants during local testing.
    if cmd.startswith("0103") or cmd.startswith("0104"):
        response_hex = generate_fake_humidity_temp_hex()
        store_uplink(device_id, response_hex, fport)
        return
    
    # Tilt/acceleration command family.
    if cmd.startswith("50"):
        # Angle read command.
        if cmd == "5003003D00039986":
            response_hex = generate_fake_angles_hex()
            store_uplink(device_id, response_hex, fport)
        # Acceleration read command.
        elif cmd == "5003003400034984":
            response_hex = generate_fake_accel_hex()
            store_uplink(device_id, response_hex, fport)
        # Mirror the real DTU behavior: unlock is echoed back as an uplink.
        elif cmd == "50060069B58822A1":
            store_uplink(device_id, cmd, fport)
        return
    
    # Water level command family.
    if cmd.startswith("7B03"):
        response_hex = generate_fake_water_level_hex()
        store_uplink(device_id, response_hex, fport)
        return


def store_uplink(device_id: str, hex_data: str, fport: int = 1):
    """Store an uplink for later retrieval."""
    with uplinks_lock:
        uplink = {
            "insertTime": generate_timestamp(),
            "data": hex_to_base64(hex_data),
            "fPort": fport
        }
        device_uplinks[device_id].insert(0, uplink)  # newest first
        # Keep only recent 50 uplinks
        device_uplinks[device_id] = device_uplinks[device_id][:50]


def generate_mmwave_uplinks_periodically():
    """Background thread to generate mmWave uplinks periodically."""
    MMWAVE_EUI = "8695311001412450"
    while True:
        time.sleep(1.0)  # Every 1 second
        if not _fake_uplink_enabled():
            continue
        if random.random() < 0.8:  # 80% chance to generate
            response_hex = generate_fake_mmwave_hex(max_targets=3)
            store_uplink(MMWAVE_EUI, response_hex, fport=1)


# Start mmWave background thread
mmwave_thread = threading.Thread(target=generate_mmwave_uplinks_periodically, daemon=True)
mmwave_thread.start()


# Public API endpoints matching the real gateway surface.

@app.route('/api/v1/internal/auth', methods=['POST'])
def authenticate():
    """Authenticate and return fake JWT token."""
    data = request.get_json()
    account = data.get('account')
    password = data.get('password')

    if not _fake_auth_ok():
        return jsonify({"error": "Forced auth failure"}), 401
    
    # Accept any credentials for testing
    if account and password:
        return jsonify({
            "token": "FAKE_JWT_TOKEN_" + str(int(time.time()))
        }), 200
    
    return jsonify({"error": "Invalid credentials"}), 401


@app.route('/api/v1/devices/<device_id>/queue', methods=['POST'])
def send_downlink(device_id: str):
    """Send downlink command to device."""
    data = request.get_json()
    hex_data = data.get('data', '')
    fport = data.get('fPort', 1)
    reference = data.get('reference', '')

    if not _fake_queue_ok():
        return jsonify({"status": "forced_queue_failure"}), 500
    
    # Simulate packet loss
    if random.random() < SIM_PACKET_LOSS_RATE:
        print(f"[FAKE] Packet loss! Downlink to {device_id} dropped")
        return jsonify({"status": "packet_lost"}), 200
    
    # Process downlink (may be delayed)
    if SIM_DELAY_SEC > 0 and random.random() < 0.3:
        def delayed():
            time.sleep(SIM_DELAY_SEC)
            process_downlink(device_id, hex_data, fport)
        threading.Thread(target=delayed, daemon=True).start()
    else:
        process_downlink(device_id, hex_data, fport)

    return jsonify({
        "status": "success",
        "device_id": device_id,
        "reference": reference
    }), 200


@app.route('/api/v1/uplink-storage/devices/<device_id>/uplink', methods=['GET'])
def get_uplinks(device_id: str):
    """Retrieve uplinks for a device."""
    size = int(request.args.get('size', 10))
    page = int(request.args.get('page', 1))
    
    with uplinks_lock:
        uplinks = device_uplinks.get(device_id, [])
        # Simple pagination (page 1 = most recent)
        start_idx = (page - 1) * size
        end_idx = start_idx + size
        result = uplinks[start_idx:end_idx]
    
    return jsonify({
        "result": result,
        "totalCount": len(result)
    }), 200


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "server": "fake_lora_gateway",
        "timestamp": generate_timestamp()
    }), 200


if __name__ == '__main__':
    # Standalone entry point for local integration testing.
    print("=" * 60)
    print("Fake LoRa Gateway Server")
    print("=" * 60)
    print("Server running at: http://127.0.0.1:5000")
    print("\nTo use this fake server, configure communicator.py:")
    print("  BASE_URL = 'http://127.0.0.1:5000/api'")
    print("\nEndpoints:")
    print("  POST /api/v1/internal/auth")
    print("  POST /api/v1/devices/<device_id>/queue")
    print("  GET  /api/v1/uplink-storage/devices/<device_id>/uplink")
    print("  GET  /health")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=5000, debug=False)
