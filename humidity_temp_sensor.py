"""
Humidity and Temperature Sensor Data Parser
Parses Modbus RTU response frames from LoRa-connected environmental sensors.
"""

import struct
from typing import Optional, Dict, Any


class HumidityTempSensor:
    """
    Humidity and Temperature Sensor Profile.
    Only handles command byte generation and response decoding.
    """

    # Modbus command to read 3 registers: T, H, D
    MODBUS_READ_CMD = "010400000003B00B"

    @classmethod
    def encode_read_command(cls) -> str:
        """Generate the Modbus read command bytes as hex string."""
        return cls.MODBUS_READ_CMD

    @staticmethod
    def _crc16_modbus(data: bytes) -> int:
        """
        Calculate Modbus RTU CRC16 checksum.

        Args:
            data: Bytes to calculate CRC for

        Returns:
            int: 16-bit CRC value
        """
        crc = 0xFFFF
        for b in data:
            crc ^= b
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc & 0xFFFF

    @staticmethod
    def _int16_be(b: bytes) -> int:
        """
        Convert 2 bytes (Big Endian) to signed 16-bit integer.

        Args:
            b: 2 bytes to convert

        Returns:
            int: Signed 16-bit integer
        """
        return struct.unpack(">h", b)[0]

    @staticmethod
    def _uint16_be(b: bytes) -> int:
        """
        Convert 2 bytes (Big Endian) to unsigned 16-bit integer.

        Args:
            b: 2 bytes to convert

        Returns:
            int: Unsigned 16-bit integer
        """
        return struct.unpack(">H", b)[0]

    def validate_response(self, hex_data: str) -> bool:
        """Temporary passthrough validator (accept all responses)."""
        return True

    def parse_humidity_sensor_data(self, data) -> Optional[Dict[str, Any]]:
        """Parsing helper removed; use decode_response instead."""
        raise NotImplementedError("parse_humidity_sensor_data is not implemented in this profile.")

    def decode_response(self, data) -> Optional[Dict[str, Any]]:
        """Decode response bytes/hex into sensor values."""
        if isinstance(data, str):
            try:
                data = bytes.fromhex(data)
            except ValueError:
                print("Error: Invalid hex string")
                return None

        if len(data) < 5:
            print(f"Error: Frame too short ({len(data)} bytes)")
            return None

        func_code = data[1]
        if func_code not in (0x03, 0x04):
            print(f"Error: Unknown Modbus function code: 0x{func_code:02X}")
            return None

        frame_len = len(data)
        data_end = frame_len - 2
        frame_without_crc = data[:data_end]

        received_crc_bytes = data[data_end:]
        received_crc = (received_crc_bytes[1] << 8) | received_crc_bytes[0]
        calculated_crc = self._crc16_modbus(frame_without_crc)
        crc_valid = (calculated_crc == received_crc)

        byte_count = data[2]
        data_bytes = data[3:3 + byte_count]

        if len(data_bytes) < 6:
            print(f"Error: Data byte count mismatch. Expected 6, got {len(data_bytes)}")
            return None

        try:
            t_raw = self._int16_be(data_bytes[0:2])
            temperature_c = t_raw / 100.0

            h_raw = self._uint16_be(data_bytes[2:4])
            humidity_rh = h_raw / 100.0

            d_raw = self._int16_be(data_bytes[4:6])
            dewpoint_c = d_raw / 100.0

            return {
                "temperature_c": temperature_c,
                "humidity_rh": humidity_rh,
                "dewpoint_c": dewpoint_c,
                "crc_valid": crc_valid,
                "raw_hex": data.hex()
            }

        except Exception as e:
            print(f"Error during value parsing: {e}")
            return None
