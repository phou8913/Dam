import struct
from typing import Optional, Dict, Any

from .base import SensorProfile
from .modbus_utils import crc16_modbus


class HWT901BSensor(SensorProfile):

    @classmethod
    def build_request(cls, mode: str = "angles") -> bytes:
        if mode == "unlock":
            return bytes.fromhex("50060069B58822A1")
        if mode == "angles":
            return bytes.fromhex("5003003D00039986")
        if mode == "accel":
            return bytes.fromhex("5003003400034984")
        raise ValueError("Unknown mode")

    def decode_response(self, data, mode: str = "angles") -> Optional[Dict[str, Any]]:
        """Decode response bytes/hex into IMU values."""
        if isinstance(data, str):
            try:
                data = bytes.fromhex(data)
            except ValueError:
                print("Error: Invalid hex string")
                return None

        try:
            expected_crc = crc16_modbus(data[:-2])
            actual_crc = int.from_bytes(data[-2:], byteorder="little")
            if mode == "angles":
                return {
                    "roll": struct.unpack(">h", data[3:5])[0] / 32768 * 180,
                    "pitch": struct.unpack(">h", data[5:7])[0] / 32768 * 180,
                    "yaw": struct.unpack(">h", data[7:9])[0] / 32768 * 180,
                    "crc_valid": actual_crc == expected_crc,
                    "raw_hex": data.hex()
                }

            if mode == "accel":
                return {
                    "ax_g": struct.unpack(">h", data[3:5])[0] / 32768 * 16,
                    "ay_g": struct.unpack(">h", data[5:7])[0] / 32768 * 16,
                    "az_g": struct.unpack(">h", data[7:9])[0] / 32768 * 16,
                    "crc_valid": actual_crc == expected_crc,
                    "raw_hex": data.hex()
                }

            if mode == "unlock":
                return {"status": "unlock_ack"}

            raise ValueError("Unknown mode")
        except Exception as e:
            print(f"Error parsing IMU response: {e}")
            return None

    ### Only used in legacy test tools, later they will be deleted in favor of build_request() with mode parameter
    @classmethod
    def encode_unlock_command(cls) -> str:
        """Compatibility wrapper for tools that still expect a hex command."""
        return cls.build_request("unlock").hex()

    @classmethod
    def encode_read_angles_command(cls) -> str:
        """Compatibility wrapper for tools that still expect a hex command."""
        return cls.build_request("angles").hex()

    @classmethod
    def encode_read_accel_command(cls) -> str:
        """Compatibility wrapper for tools that still expect a hex command."""
        return cls.build_request("accel").hex()
