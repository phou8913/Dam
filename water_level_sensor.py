"""
Water Level Sensor
Modbus RTU parser for LoRa-connected water level sensor.
Reads float value representing water level in meters.
"""

import struct
from typing import Optional, Dict, Any


class WaterLevelSensor:
    """
    Water Level Sensor Profile.
    Only handles command byte generation and response decoding.
    """

    SLAVE_ADDR = 123

    @classmethod
    def encode_read_command(cls) -> str:
        """Generate the Modbus read command bytes as hex string."""
        return cls._make_read_command()

    @staticmethod
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

    @classmethod
    def _make_read_command(cls) -> str:
        """
        Create Modbus RTU read holding registers command.
        Slave: 123, Function: 0x03, Start: 0x0000, Count: 0x0002
        """
        frame = struct.pack('>BBHH', cls.SLAVE_ADDR, 0x03, 0x0000, 0x0002)
        crc = cls._crc16_modbus(frame)
        crc_bytes = struct.pack('<H', crc)
        full_frame = frame + crc_bytes
        return full_frame.hex()

    def validate_response(self, hex_data: str) -> bool:
        """Temporary passthrough validator (accept all responses)."""
        return True

    def parse_water_level(self, data) -> Optional[Dict[str, Any]]:
        """Parsing helper removed; use decode_response instead."""
        raise NotImplementedError("parse_water_level is not implemented in this profile.")

    def decode_response(self, data) -> Optional[Dict[str, Any]]:
        """Decode response bytes/hex into water level value."""
        if isinstance(data, str):
            try:
                data = bytes.fromhex(data)
            except ValueError:
                print("Error: Invalid hex string")
                return None

        if len(data) < 9:
            print(f"Error: Response too short ({len(data)} bytes, expected >= 9)")
            return None

        func_code = data[1]
        if func_code != 0x03:
            print(f"Error: Unknown function code: 0x{func_code:02X}")
            return None

        frame_len = len(data)
        data_end = frame_len - 2
        frame_without_crc = data[:data_end]

        received_crc_bytes = data[data_end:]
        received_crc = (received_crc_bytes[1] << 8) | received_crc_bytes[0]
        calculated_crc = self._crc16_modbus(frame_without_crc)
        crc_valid = (calculated_crc == received_crc)

        byte_count = data[2]
        if byte_count != 4:
            print(f"Error: Expected 4 data bytes, got {byte_count}")
            return None

        data_bytes = data[3:7]

        try:
            level_m = struct.unpack('>f', data_bytes)[0]

            return {
                "level_m": level_m,
                "crc_valid": crc_valid,
                "raw_hex": data.hex()
            }

        except Exception as e:
            print(f"Error parsing water level: {e}")
            return None