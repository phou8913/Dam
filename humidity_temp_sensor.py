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
        """
        Strong validator: check Modbus frame integrity.
        Expected: [01][04][06][T_Hi][T_Lo][H_Hi][H_Lo][D_Hi][D_Lo][CRC_Lo][CRC_Hi]
        """
        try:
            data = bytes.fromhex(hex_data)
            
            # Minimum frame length
            if len(data) < 11:
                return False
            
            # Check function code (0x04 = Read Input Registers)
            if data[1] != 0x04:
                return False
            
            # Check byte count (should be 0x06 for 3 registers)
            if data[2] != 0x06:
                return False
            
            # Validate CRC
            frame_len = len(data)
            data_end = frame_len - 2
            frame_without_crc = data[:data_end]
            received_crc_bytes = data[data_end:]
            received_crc = (received_crc_bytes[1] << 8) | received_crc_bytes[0]
            calculated_crc = self._crc16_modbus(frame_without_crc)
            
            return calculated_crc == received_crc
        except Exception as e:
            print(f"[HumidityTempSensor] Validator error: {e}")
            return False

    def parse_humidity_sensor_data(self, data) -> Optional[Dict[str, Any]]:
        """
        Parse humidity sensor data from raw Modbus RTU response frame.

        Expected Modbus RTU frame format:
        [Addr][Func=03/04][Byte Count=06][T_Hi][T_Lo][H_Hi][H_Lo][D_Hi][D_Lo][CRC_Lo][CRC_Hi]

        Args:
            data: Raw bytes or hex string from Modbus RTU response

        Returns:
            dict: Parsed sensor data or None if parsing fails
        """
        # Convert hex string to bytes if needed
        if isinstance(data, str):
            try:
                data = bytes.fromhex(data)
            except ValueError:
                print("Error: Invalid hex string")
                return None

        # Validate minimum frame length
        if len(data) < 5:
            print(f"Error: Frame too short ({len(data)} bytes)")
            return None

        # Check function code (0x03 = Read Holding Registers, 0x04 = Read Input Registers)
        func_code = data[1]
        if func_code not in (0x03, 0x04):
            print(f"Error: Unknown Modbus function code: 0x{func_code:02X}")
            return None

        # Validate CRC
        frame_len = len(data)
        data_end = frame_len - 2
        frame_without_crc = data[:data_end]

        # Modbus CRC is Little Endian: Low byte first, High byte second
        received_crc_bytes = data[data_end:]
        received_crc = (received_crc_bytes[1] << 8) | received_crc_bytes[0]
        calculated_crc = self._crc16_modbus(frame_without_crc)
        crc_valid = (calculated_crc == received_crc)

        # Extract data payload
        byte_count = data[2]
        data_bytes = data[3:3 + byte_count]

        # Expect 6 bytes of data for 3 registers (T, H, D)
        if len(data_bytes) < 6:
            print(f"Error: Data byte count mismatch. Expected 6, got {len(data_bytes)}")
            return None

        try:
            # Parse Temperature: Register 0x0000 (INT16, Big Endian)
            t_raw = self._int16_be(data_bytes[0:2])
            temperature_c = t_raw / 100.0

            # Parse Humidity: Register 0x0001 (UINT16, Big Endian)
            h_raw = self._uint16_be(data_bytes[2:4])
            humidity_rh = h_raw / 100.0

            # Parse Dewpoint: Register 0x0002 (INT16, Big Endian)
            d_raw = self._int16_be(data_bytes[4:6])
            dewpoint_c = d_raw / 100.0

            # Return parsed data as dictionary
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

    def decode_response(self, data) -> Optional[Dict[str, Any]]:
        """Decode response bytes/hex into sensor values."""
        return self.parse_humidity_sensor_data(data)
