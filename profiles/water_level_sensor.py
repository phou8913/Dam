import struct
from typing import Optional, Dict, Any, List

from .base import SensorProfile
from .modbus_utils import crc16_modbus


class WaterLevelSensor(SensorProfile):

    SLAVE_ADDR = 123

    @classmethod
    def build_request(cls, mode: str = "read") -> bytes:
        if mode != "read":
            raise ValueError("Unsupported mode")

        frame = struct.pack(">BBHH", cls.SLAVE_ADDR, 0x03, 0x0000, 0x0002)
        crc = crc16_modbus(frame)
        return frame + struct.pack("<H", crc)

    def decode_response(self, data, mode: str = "read") -> Optional[Dict[str, Any]]:
        """Decode response bytes/hex into water level value."""
        if mode != "read":
            raise ValueError("Unsupported mode")

        if isinstance(data, str):
            try:
                data = bytes.fromhex(data)
            except ValueError:
                print("Error: Invalid hex string")
                return None

        try:
            return {
                "level_m": struct.unpack(">f", data[3:7])[0],
                "raw_hex": data.hex()
            }
        except Exception as e:
            print(f"Error parsing water level: {e}")
            return None

    ### Only used in legacy test tools, later they will be deleted in favor of build_request() with mode parameter
    @classmethod
    def encode_read_command(cls) -> str:
        """Compatibility wrapper for tools that still expect a hex command."""
        return cls.build_request("read").hex()
