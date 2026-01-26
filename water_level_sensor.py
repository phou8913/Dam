"""
Water Level Sensor
Modbus RTU parser for LoRa-connected water level sensor.
Reads float value representing water level in meters.
"""

import struct
import time
from typing import Optional, Dict, Any

import communicator


class WaterLevelSensor:
    """
    Water Level Sensor Interface.
    Handles water level data retrieval and parsing from Modbus device.
    """

    SLAVE_ADDR = 123

    def __init__(self, dev_eui: str, token=None):
        """
        Initialize the sensor with device EUI.

        Args:
            dev_eui: Device EUI identifier for the LoRa sensor
            token: Optional JWT token
        """
        self.dev_eui = dev_eui
        self._token = token
        self._read_cmd = self._make_read_command()

    def _ensure_token(self):
        """Ensure we have a valid authentication token."""
        if self._token is None:
            self._token = communicator.get_token()
        return self._token

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

    def _make_read_command(self) -> str:
        """
        Create Modbus RTU read holding registers command.
        Slave: 123, Function: 0x03, Start: 0x0000, Count: 0x0002
        """
        frame = struct.pack('>BBHH', self.SLAVE_ADDR, 0x03, 0x0000, 0x0002)
        crc = self._crc16_modbus(frame)
        crc_bytes = struct.pack('<H', crc)
        full_frame = frame + crc_bytes
        return full_frame.hex()

    def parse_water_level(self, data) -> Optional[Dict[str, Any]]:
        """
        Parse water level data from Modbus response.

        Response format:
        [Addr][Func=0x03][Byte Count=4][Float32 Big-Endian][CRC_Lo][CRC_Hi]

        Args:
            data: Raw bytes or hex string from Modbus response

        Returns:
            dict: Parsed water level data or None if parsing fails
        """
        if isinstance(data, str):
            try:
                data = bytes.fromhex(data)
            except ValueError:
                print("Error: Invalid hex string")
                return None

        if len(data) < 9:
            print(f"Error: Response too short ({len(data)} bytes, expected >= 9)")
            return None

        # Check function code
        func_code = data[1]
        if func_code != 0x03:
            print(f"Error: Unknown function code: 0x{func_code:02X}")
            return None

        # Validate CRC
        frame_len = len(data)
        data_end = frame_len - 2
        frame_without_crc = data[:data_end]

        received_crc_bytes = data[data_end:]
        received_crc = (received_crc_bytes[1] << 8) | received_crc_bytes[0]
        calculated_crc = self._crc16_modbus(frame_without_crc)
        crc_valid = (calculated_crc == received_crc)

        # Extract data bytes
        byte_count = data[2]
        if byte_count != 4:
            print(f"Error: Expected 4 data bytes, got {byte_count}")
            return None

        data_bytes = data[3:7]

        try:
            # Parse as big-endian float (4 bytes)
            level_m = struct.unpack('>f', data_bytes)[0]

            return {
                "level_m": level_m,
                "crc_valid": crc_valid,
                "raw_hex": data.hex()
            }

        except Exception as e:
            print(f"Error parsing water level: {e}")
            return None

    def read_data(
            self,
            max_attempts: int = 12,
            poll_interval: int = 5
    ) -> Optional[Dict[str, Any]]:
        """
        Read water level data from the device.

        Args:
            max_attempts: Maximum number of polling attempts
            poll_interval: Seconds to wait between polling attempts

        Returns:
            dict: Parsed water level data or None if reading fails
        """
        try:
            token = self._ensure_token()

            status, response = communicator.send_request(
                device_id=self.dev_eui,
                data_to_send=self._read_cmd,
                auth_token=token
            )

            if status != 1:
                print(f"Failed to send read command")
                return None

            for attempt in range(1, max_attempts + 1):
                time.sleep(poll_interval)

                status, hex_data = communicator.pull_latest_data(
                    device_id=self.dev_eui,
                    auth_token=token,
                    size=10
                )

                if status == 1 and hex_data:
                    parsed_data = self.parse_water_level(hex_data)
                    return parsed_data

            print(f"No response received after {max_attempts} attempts")
            return None

        except Exception as e:
            print(f"Error reading water level: {e}")
            return None


if __name__ == "__main__":
    DEV_EUI = "8695311000942380"

    sensor = WaterLevelSensor(dev_eui=DEV_EUI)
    data = sensor.read_data()

    if data:
        print(f"Water Level: {data['level_m']:.3f} m")
        print(f"CRC Valid: {data['crc_valid']}")
        print(f"Raw: {data['raw_hex']}")
    else:
        print("Failed to read water level")