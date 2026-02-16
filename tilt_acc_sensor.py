"""
HWT901B Angle and Acceleration Sensor
Modbus RTU parser for LoRa-connected IMU sensor.
"""

import struct
from typing import Optional, Dict, Any


class HWT901BSensor:
    """
    HWT901B IMU Sensor Profile.
    Only handles command byte generation and response decoding.
    """

    UNLOCK_CMD = "50060069B58822A1"
    READ_ANGLES_CMD = "5003003D00039986"
    READ_ACCEL_CMD = "5003003400034984"

    @classmethod
    def encode_unlock_command(cls) -> str:
        """Generate unlock command bytes as hex string."""
        return cls.UNLOCK_CMD

    @classmethod
    def encode_read_angles_command(cls) -> str:
        """Generate read-angles command bytes as hex string."""
        return cls.READ_ANGLES_CMD

    @classmethod
    def encode_read_accel_command(cls) -> str:
        """Generate read-accel command bytes as hex string."""
        return cls.READ_ACCEL_CMD

    @staticmethod
    def _int16_be(b: bytes) -> int:
        """Convert 2 bytes (Big Endian) to signed 16-bit integer."""
        return struct.unpack(">h", b)[0]

    def validate_angles_response(self, hex_data: str) -> bool:
        """Temporary passthrough validator (accept all responses)."""
        return True

    def validate_accel_response(self, hex_data: str) -> bool:
        """Temporary passthrough validator (accept all responses)."""
        return True

    def parse_angles(self, data) -> Optional[Dict[str, Any]]:
        """Parsing helper removed; use decode_angles instead."""
        raise NotImplementedError("parse_angles is not implemented in this profile.")

    def parse_acceleration(self, data) -> Optional[Dict[str, Any]]:
        """Parsing helper removed; use decode_acceleration instead."""
        raise NotImplementedError("parse_acceleration is not implemented in this profile.")

    def decode_angles(self, data) -> Optional[Dict[str, Any]]:
        """Decode response bytes/hex into roll/pitch/yaw."""
        if isinstance(data, str):
            try:
                data = bytes.fromhex(data)
            except ValueError:
                print("Error: Invalid hex string")
                return None

        if len(data) < 11:
            print("Error: Insufficient data for angles")
            return None

        try:
            roll_raw = self._int16_be(data[3:5])
            pitch_raw = self._int16_be(data[5:7])
            yaw_raw = self._int16_be(data[7:9])

            roll = (roll_raw / 32768.0) * 180.0
            pitch = (pitch_raw / 32768.0) * 180.0
            yaw = (yaw_raw / 32768.0) * 180.0

            return {
                "roll": roll,
                "pitch": pitch,
                "yaw": yaw,
                "raw_hex": data.hex()
            }

        except Exception as e:
            print(f"Error parsing angles: {e}")
            return None

    def decode_acceleration(self, data) -> Optional[Dict[str, Any]]:
        """Decode response bytes/hex into acceleration values."""
        if isinstance(data, str):
            try:
                data = bytes.fromhex(data)
            except ValueError:
                print("Error: Invalid hex string")
                return None

        if len(data) < 11:
            print("Error: Insufficient data for acceleration")
            return None

        try:
            ax_raw = self._int16_be(data[3:5])
            ay_raw = self._int16_be(data[5:7])
            az_raw = self._int16_be(data[7:9])

            ax = (ax_raw / 32768.0) * 16.0
            ay = (ay_raw / 32768.0) * 16.0
            az = (az_raw / 32768.0) * 16.0

            return {
                "ax_g": ax,
                "ay_g": ay,
                "az_g": az,
                "ax_ms2": ax * 9.8,
                "ay_ms2": ay * 9.8,
                "az_ms2": az * 9.8,
                "raw_hex": data.hex()
            }

        except Exception as e:
            print(f"Error parsing acceleration: {e}")
            return None
