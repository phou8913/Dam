"""
Humidity and Temperature Sensor Data Parser
Parses Modbus RTU response frames from LoRa-connected environmental sensors.
"""

import struct
import time
from typing import Optional, Dict, Any

# Import the communicator module for API interaction
import communicator


class HumidityTempSensor:
    """
    Humidity and Temperature Sensor Interface.
    Handles communication, Modbus RTU response parsing, and data retrieval.
    """

    # Modbus command to read 3 registers: T, H, D
    MODBUS_READ_CMD = "010400000003B00B"

    def __init__(self, dev_eui: str, token=None, min_send_interval_sec: float = 1.0):
        """
        Initialize the sensor with device EUI.

        Args:
            dev_eui: Device EUI identifier for the LoRa sensor
            token: Optional JWT token
            min_send_interval_sec: Minimum interval (seconds) between sends to this DTU
        """
        self.dev_eui = dev_eui
        self._token = token
        self.min_send_interval_sec = min_send_interval_sec

    def _ensure_token(self):
        """Ensure we have a valid authentication token."""
        if self._token is None:
            self._token = communicator.get_token()
        return self._token

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

    def _validate_response(self, hex_data: str) -> bool:
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

    def read_data(
        self,
        timeout_sec: float = 30.0,
        poll_interval_sec: float = 1.0
    ) -> Optional[Dict[str, Any]]:
        """
        Read live sensor data using send_and_wait (request-response matching).

        Args:
            timeout_sec: Timeout in seconds
            poll_interval_sec: Polling interval in seconds

        Returns:
            dict: Parsed sensor data or None if reading fails
        """
        try:
            token = self._ensure_token()

            # Use send_and_wait with strong response validator
            status, hex_data = communicator.send_and_wait(
                device_id=self.dev_eui,
                data_to_send=self.MODBUS_READ_CMD,
                auth_token=token,
                response_validator=self._validate_response,
                timeout_sec=timeout_sec,
                fport=1,
                reference="humidity-read",
                min_interval_sec=self.min_send_interval_sec,
                poll_interval_sec=poll_interval_sec
            )

            if status != 1 or hex_data is None:
                print(f"Failed to read from device {self.dev_eui}")
                return None

            parsed_data = self.parse_humidity_sensor_data(hex_data)
            return parsed_data

        except Exception as e:
            print(f"Error reading sensor data: {e}")
            return None


# ============ Main ============

if __name__ == "__main__":
    DEV_EUI = "8695311000931640"

    sensor = HumidityTempSensor(dev_eui=DEV_EUI)
    data = sensor.read_data()

    if data:
        print(f"Temperature: {data['temperature_c']:.2f} °C")
        print(f"Humidity: {data['humidity_rh']:.2f} %RH")
        print(f"Dewpoint: {data['dewpoint_c']:.2f} °C")
        print(f"CRC Valid: {data['crc_valid']}")
        print(f"Raw: {data['raw_hex']}")
    else:
        print("Failed to read sensor data")