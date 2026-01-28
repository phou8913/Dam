# fake_communicator.py
import time
import struct
import random
import math
import threading
from typing import Optional, Tuple, Any, Dict, List


# Global lock and timestamp for ensuring unique timestamps
_TIMESTAMP_LOCK = threading.Lock()
_LAST_GLOBAL_TS = 0.0


def _get_unique_timestamp() -> float:
    """Get a unique, monotonically increasing timestamp."""
    global _LAST_GLOBAL_TS
    with _TIMESTAMP_LOCK:
        current_ts = time.time()
        if current_ts <= _LAST_GLOBAL_TS:
            current_ts = _LAST_GLOBAL_TS + 0.000001
        _LAST_GLOBAL_TS = current_ts
        return current_ts


# -----------------------------
# Helpers (CRC16 Modbus)
# -----------------------------
def _crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def _append_crc_le(frame_wo_crc: bytes) -> bytes:
    crc = _crc16_modbus(frame_wo_crc)
    return frame_wo_crc + struct.pack("<H", crc)  # little-endian


# -----------------------------
# Fake DTU base
# -----------------------------
class FakeDTU:
    """
    Each DTU maintains its own uplink queue (newest first).
    Each uplink now carries: {ts, hex, fport}
    """
    def __init__(self, dev_eui: str):
        self.dev_eui = dev_eui
        self._uplinks: List[Dict[str, Any]] = []  # dicts with ts, hex, fport
        self._last_downlink: Optional[Dict[str, Any]] = None

    def on_downlink(self, data_to_send_hex: str, fport: int, reference: str) -> None:
        self._last_downlink = {
            "data": data_to_send_hex,
            "fport": fport,
            "reference": reference,
            "ts": time.time(),
        }

    def generate_uplink_if_needed(self) -> None:
        """
        For passive devices (e.g. mmWave), they can periodically push uplinks here.
        For request/response devices, they can push uplinks in on_downlink.
        """
        return

    def push_uplink_hex(self, payload_hex: str, fport: int = 1) -> None:
        """Push uplink with unique, monotonically increasing timestamp."""
        uplink = {
            "ts": _get_unique_timestamp(),
            "hex": payload_hex,
            "fport": fport
        }
        self._uplinks.insert(0, uplink)  # newest at front
        # keep recent history
        self._uplinks = self._uplinks[:50]

    def pull_latest(self, size: int = 10) -> Optional[str]:
        """Pull latest uplink hex (backward compat)."""
        self.generate_uplink_if_needed()
        if not self._uplinks:
            return None
        return self._uplinks[0]["hex"]

    def pull_latest_uplinks(self, size: int = 10) -> Optional[List[Dict[str, Any]]]:
        """Pull latest uplinks with full metadata."""
        self.generate_uplink_if_needed()
        if not self._uplinks:
            return None
        return self._uplinks[:size]


# -----------------------------
# Fake Humidity/Temp DTU
# Generates Modbus 0x04 response:
# [01][04][06][T_hi][T_lo][H_hi][H_lo][D_hi][D_lo][CRC_lo][CRC_hi]
# -----------------------------
class FakeHumidityTempDTU(FakeDTU):
    def on_downlink(self, data_to_send_hex: str, fport: int, reference: str) -> None:
        super().on_downlink(data_to_send_hex, fport, reference)

        # simulate values
        temp_c = 18.0 + random.random() * 10.0
        hum_rh = 30.0 + random.random() * 40.0
        dew_c = temp_c - (100.0 - hum_rh) / 10.0

        t_raw = int(temp_c * 100)
        h_raw = int(hum_rh * 100)
        d_raw = int(dew_c * 100)

        payload = struct.pack(">BBBhHh", 0x01, 0x04, 0x06, t_raw, h_raw, d_raw)
        frame = _append_crc_le(payload)
        self.push_uplink_hex(frame.hex(), fport=1)


# -----------------------------
# Fake Tilt/Acc DTU
# Your parsers do NOT validate CRC; they only read bytes[3:9].
# We'll generate two response flavors based on which command was sent.
# - angles: roll/pitch/yaw raw int16 at [3:9]
# - accel:  ax/ay/az raw int16 at [3:9]
# -----------------------------
class FakeTiltAccDTU(FakeDTU):
    READ_ANGLES_CMD = "5003003D00039986"
    READ_ACCEL_CMD = "5003003400034984"
    READ_GPS_CMD = "500300490004985E"
    RESET_CMD    = "5006000000FFC40B"

    def on_downlink(self, data_to_send_hex: str, fport: int, reference: str) -> None:
        super().on_downlink(data_to_send_hex, fport, reference)

        # Frame header consistent with your expectation: at least 11 bytes
        # We'll set: [0]=0x50, [1]=0x03, [2]=0x06, then 6 data bytes, then 2 pad bytes.
        header = bytes([0x50, 0x03, 0x06])

        if data_to_send_hex.upper() == self.READ_ANGLES_CMD:
            # generate roll/pitch/yaw in degrees (-90..90)
            roll = random.uniform(-10, 10)
            pitch = random.uniform(-10, 10)
            yaw = random.uniform(-10, 10)

            # inverse of your decode: deg = raw/32768*180 => raw = deg/180*32768
            def to_raw(deg: float) -> int:
                return int(deg / 180.0 * 32768)

            data6 = struct.pack(">hhh", to_raw(roll), to_raw(pitch), to_raw(yaw))
            frame = header + data6 + b"\x00\x00"
            self.push_uplink_hex(frame.hex(), fport=1)
            return

        if data_to_send_hex.upper() == self.READ_ACCEL_CMD:
            # generate ax/ay/az in g (-2..2)
            ax = random.uniform(-0.5, 0.5)
            ay = random.uniform(-0.5, 0.5)
            az = random.uniform(-0.5, 0.5)

            # inverse of your decode: g = raw/16*32768 => raw = g/16*32768
            def to_raw(g: float) -> int:
                return int(g / 16.0 * 32768)

            data6 = struct.pack(">hhh", to_raw(ax), to_raw(ay), to_raw(az))
            frame = header + data6 + b"\x00\x00"
            self.push_uplink_hex(frame.hex(), fport=1)
            return
        
        # New GPS command handling
        if data_to_send_hex.replace(" ", "").upper() == self.READ_GPS_CMD:
            lat = random.uniform(33.0, 35.0)
            lon = random.uniform(-85.0, -83.0)
            spd = random.uniform(0.0, 30.0)

            lat_raw = int(lat * 100)
            lon_raw = int(lon * 100)
            spd_raw = int(spd * 10)

            data6 = struct.pack(">hhh", lat_raw, lon_raw, spd_raw)
            frame = header + data6 + b"\x00\x00"
            self.push_uplink_hex(frame.hex(), fport=1)
            return
        
        # New Reset command handling
        if data_to_send_hex.replace(" ", "").upper() == self.RESET_CMD:
            self._uplinks.clear()
            data6 = b"\x00\x00\x00\x00\x00\x01"
            frame = bytes([0x50, 0x06, 0x02]) + data6 + b"\x00\x00"
            self.push_uplink_hex(frame.hex(), fport=1)
            return

        # Unknown downlink: do nothing
        return


# -----------------------------
# Fake Water Level DTU
# Expected response:
# [Addr=123][Func=03][ByteCount=4][Float32 BE][CRC_lo][CRC_hi]
# -----------------------------
class FakeWaterLevelDTU(FakeDTU):
    SLAVE_ADDR = 123
    _lock = threading.Lock()  # Per-class lock to serialize on_downlink calls

    def on_downlink(self, data_to_send_hex: str, fport: int, reference: str) -> None:
        super().on_downlink(data_to_send_hex, fport, reference)

        # Serialize the entire generation and push process to avoid race conditions
        with self._lock:
            level_m = random.uniform(0.05, 0.50)
            header = struct.pack(">BBB", self.SLAVE_ADDR, 0x03, 0x04)
            data4 = struct.pack(">f", float(level_m))
            frame_wo_crc = header + data4
            frame = _append_crc_le(frame_wo_crc)
            self.push_uplink_hex(frame.hex(), fport=1)


# -----------------------------
# Fake mmWave DTU (passive, continuous uplinks)
# Your parser expects 4 bytes per target:
# [Dist_hi][Dist_lo][Angle_hi][Angle_lo] ... (big-endian)
# distance_raw is /1000 => meters
# angle_raw is signed16 then /100 => degrees
# -----------------------------
class FakeMMWaveDTU(FakeDTU):
    def __init__(self, dev_eui: str, period_sec: float = 1.0):
        super().__init__(dev_eui)
        self.period_sec = period_sec
        self._next_ts = 0.0

    def generate_uplink_if_needed(self) -> None:
        now = time.time()
        if now < self._next_ts:
            return
        self._next_ts = now + self.period_sec

        # 0~3 targets
        n = random.randint(0, 3)
        if n == 0:
            # simulate "no detection" by not pushing anything
            return

        payload = b""
        for _ in range(n):
            distance_m = random.uniform(0.2, 5.0)
            distance_raw = int(distance_m * 1000)  # meters -> raw

            angle_deg = random.uniform(-60.0, 60.0)
            angle_raw = int(angle_deg * 100)  # deg -> raw

            # pack big-endian: dist u16, angle s16
            payload += struct.pack(">Hh", distance_raw, angle_raw)

        self.push_uplink_hex(payload.hex(), fport=1)


# -----------------------------
# Shared DTU: one EUI, multiple sensors behind it
# Minimal router based on downlink command prefix
# -----------------------------
class FakeSharedDTU(FakeDTU):
    def __init__(self, dev_eui: str):
        super().__init__(dev_eui)
        # reuse your existing DTU implementations, but share one EUI
        self._ht = FakeHumidityTempDTU(dev_eui)
        self._ta = FakeTiltAccDTU(dev_eui)
        self._wl = FakeWaterLevelDTU(dev_eui)
        self._last_used: Optional[FakeDTU] = None  # remember who generated the latest uplink

    def on_downlink(self, data_to_send_hex: str, fport: int, reference: str) -> None:
        super().on_downlink(data_to_send_hex, fport, reference)

        cmd = data_to_send_hex.replace(" ", "").upper()

        # Humidity/Temp: your command starts with 0104...
        if cmd.startswith("0104"):
            self._last_used = self._ht
            self._ht.on_downlink(data_to_send_hex, fport, reference)
            return

        # Tilt/Acc: your commands start with 50...
        if cmd.startswith("50"):
            self._last_used = self._ta
            self._ta.on_downlink(data_to_send_hex, fport, reference)
            return

        # Water level: slave 123 + func 03 => 0x7B 0x03 => "7B03..."
        if cmd.startswith("7B03"):
            self._last_used = self._wl
            self._wl.on_downlink(data_to_send_hex, fport, reference)
            return

        # Unknown: do nothing
        return

    def pull_latest(self, size: int = 10) -> Optional[str]:
        # return the latest uplink from the DTU that was just used
        if self._last_used is None:
            return None
        return self._last_used.pull_latest(size=size)

    def pull_latest_uplinks(self, size: int = 10) -> Optional[List[Dict[str, Any]]]:
        """Pull latest uplinks from the DTU that was just used."""
        if self._last_used is None:
            return None
        return self._last_used.pull_latest_uplinks(size=size)


# -----------------------------
# Fake Gateway: maps dev_eui -> DTU
# -----------------------------
class FakeGateway:
    def __init__(self):
        # Use the same defaults from your GUI
        shared_eui = "8695311000942380"
        self.dtu_map: Dict[str, FakeDTU] = {
            # unified DTU for Humidity + Tilt/Acc + Water Level
            shared_eui: FakeSharedDTU(shared_eui),

            # mmWave stays separate
            "8695311001412450": FakeMMWaveDTU("8695311001412450", period_sec=0.8),
        }

    def get_or_create(self, dev_eui: str) -> FakeDTU:
        if dev_eui not in self.dtu_map:
            # default: mmWave-like passive device
            self.dtu_map[dev_eui] = FakeMMWaveDTU(dev_eui)
        return self.dtu_map[dev_eui]


_GATEWAY = FakeGateway()


# -----------------------------
# Public API: match communicator.py signatures
# -----------------------------
def get_token() -> str:
    return "FAKE_TOKEN"


def send_request(
    device_id: str,
    data_to_send: str,
    auth_token: str,
    fport: int = 1,
    reference: str = "downlink-cmd"
) -> Tuple[int, Optional[Any]]:
    dtu = _GATEWAY.get_or_create(device_id)
    dtu.on_downlink(data_to_send_hex=data_to_send, fport=fport, reference=reference)

    # mimic server response structure
    return 1, {"fake": True, "device_id": device_id, "reference": reference}


def pull_latest_data(
    device_id: str,
    auth_token: str,
    size: int = 10
) -> Tuple[int, Optional[str]]:
    """Legacy: pull single hex string (backward compat)."""
    dtu = _GATEWAY.get_or_create(device_id)
    hex_payload = dtu.pull_latest(size=size)
    if hex_payload:
        return 1, hex_payload
    return 0, None


def pull_latest_uplinks(
    device_id: str,
    auth_token: str,
    size: int = 10
) -> Tuple[int, Optional[List[Dict[str, Any]]]]:
    """Pull latest uplinks with metadata (ts, hex, fport)."""
    dtu = _GATEWAY.get_or_create(device_id)
    uplinks = dtu.pull_latest_uplinks(size=size)
    if uplinks:
        return 1, uplinks
    return 0, None
