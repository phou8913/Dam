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
        """
        Strong validator for angles response.
        Expected: [0x50][0x03][0x06] + 6 data bytes + 2 pad bytes (11+ bytes total)
        """
        try:
            data = bytes.fromhex(hex_data)
            
            if len(data) < 11:
                return False
            
            # Check frame header
            if data[0] != 0x50 or data[1] != 0x03 or data[2] != 0x06:
                return False
            
            # Valid: frame header matches expected angles response
            return True
        except Exception as e:
            print(f"[HWT901BSensor] Angles validator error: {e}")
            return False

    def validate_accel_response(self, hex_data: str) -> bool:
        """
        Strong validator for acceleration response.
        Expected: [0x50][0x03][0x06] + 6 data bytes + 2 pad bytes (11+ bytes total)
        """
        try:
            data = bytes.fromhex(hex_data)
            
            if len(data) < 11:
                return False
            
            # Check frame header (same as angles)
            if data[0] != 0x50 or data[1] != 0x03 or data[2] != 0x06:
                return False
            
            # Valid: frame header matches expected accel response
            return True
        except Exception as e:
            print(f"[HWT901BSensor] Accel validator error: {e}")
            return False

    def parse_angles(self, data) -> Optional[Dict[str, Any]]:
        """
        Parse angle data (roll, pitch, yaw) from Modbus response.

        Args:
            data: Raw bytes or hex string from Modbus response

        Returns:
            dict: Parsed angle data or None if parsing fails
        """
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

    def parse_acceleration(self, data) -> Optional[Dict[str, Any]]:
        """
        Parse acceleration data (ax, ay, az) from Modbus response.

        Args:
            data: Raw bytes or hex string from Modbus response

        Returns:
            dict: Parsed acceleration data or None if parsing fails
        """
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

    def decode_angles(self, data) -> Optional[Dict[str, Any]]:
        """Decode response bytes/hex into roll/pitch/yaw."""
        return self.parse_angles(data)

    def decode_acceleration(self, data) -> Optional[Dict[str, Any]]:
        """Decode response bytes/hex into acceleration values."""
        return self.parse_acceleration(data)
