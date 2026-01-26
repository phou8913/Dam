"""
HWT901B Angle and Acceleration Sensor
Modbus RTU parser for LoRa-connected IMU sensor.
"""

import struct
import time
from typing import Optional, Dict, Any

import communicator


class HWT901BSensor:
    """
    HWT901B IMU Sensor Interface.
    Handles angle and acceleration data retrieval and parsing.
    """

    UNLOCK_CMD = "50060069B58822A1"
    READ_ANGLES_CMD = "5003003D00039986"
    READ_ACCEL_CMD = "5003003400034984"

    def __init__(self, dev_eui: str, token=None):
        """
        Initialize the sensor with device EUI.

        Args:
            dev_eui: Device EUI identifier for the LoRa sensor
            token: Optional JWT token
        """
        self.dev_eui = dev_eui
        self._token = token

    def _ensure_token(self):
        """Ensure we have a valid authentication token."""
        if self._token is None:
            self._token = communicator.get_token()
        return self._token

    @staticmethod
    def _int16_be(b: bytes) -> int:
        """Convert 2 bytes (Big Endian) to signed 16-bit integer."""
        return struct.unpack(">h", b)[0]

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

    def read_angles(
            self,
            max_attempts: int = 12,
            poll_interval: int = 5,
            auto_unlock: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Read angle data from the device.

        Args:
            max_attempts: Maximum number of polling attempts
            poll_interval: Seconds to wait between polling attempts
            auto_unlock: Automatically send unlock command before reading

        Returns:
            dict: Parsed angle data or None if reading fails
        """
        try:
            token = self._ensure_token()

            if auto_unlock:
                status, _ = communicator.send_request(
                    device_id=self.dev_eui,
                    data_to_send=self.UNLOCK_CMD,
                    auth_token=token
                )
                if status != 1:
                    print(f"Failed to send unlock command")
                    return None
                time.sleep(0.5)

            status, _ = communicator.send_request(
                device_id=self.dev_eui,
                data_to_send=self.READ_ANGLES_CMD,
                auth_token=token
            )

            if status != 1:
                print(f"Failed to send read angles command")
                return None

            for attempt in range(1, max_attempts + 1):
                time.sleep(poll_interval)

                status, hex_data = communicator.pull_latest_data(
                    device_id=self.dev_eui,
                    auth_token=token,
                    size=10
                )

                if status == 1 and hex_data:
                    parsed_data = self.parse_angles(hex_data)
                    return parsed_data

            print(f"No response received after {max_attempts} attempts")
            return None

        except Exception as e:
            print(f"Error reading angles: {e}")
            return None

    def read_acceleration(
            self,
            max_attempts: int = 12,
            poll_interval: int = 5,
            auto_unlock: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Read acceleration data from the device.

        Args:
            max_attempts: Maximum number of polling attempts
            poll_interval: Seconds to wait between polling attempts
            auto_unlock: Automatically send unlock command before reading

        Returns:
            dict: Parsed acceleration data or None if reading fails
        """
        try:
            token = self._ensure_token()

            if auto_unlock:
                status, _ = communicator.send_request(
                    device_id=self.dev_eui,
                    data_to_send=self.UNLOCK_CMD,
                    auth_token=token
                )
                if status != 1:
                    print(f"Failed to send unlock command")
                    return None
                time.sleep(0.5)

            status, _ = communicator.send_request(
                device_id=self.dev_eui,
                data_to_send=self.READ_ACCEL_CMD,
                auth_token=token
            )

            if status != 1:
                print(f"Failed to send read acceleration command")
                return None

            for attempt in range(1, max_attempts + 1):
                time.sleep(poll_interval)

                status, hex_data = communicator.pull_latest_data(
                    device_id=self.dev_eui,
                    auth_token=token,
                    size=10
                )

                if status == 1 and hex_data:
                    parsed_data = self.parse_acceleration(hex_data)
                    return parsed_data

            print(f"No response received after {max_attempts} attempts")
            return None

        except Exception as e:
            print(f"Error reading acceleration: {e}")
            return None


if __name__ == "__main__":
    DEV_EUI = "8695311000935940"

    sensor = HWT901BSensor(dev_eui=DEV_EUI)

    print("Reading angles...")
    angles = sensor.read_angles()
    if angles:
        print(f"Roll:  {angles['roll']:.2f}°")
        print(f"Pitch: {angles['pitch']:.2f}°")
        print(f"Yaw:   {angles['yaw']:.2f}°")
    else:
        print("Failed to read angles")

    print("\nReading acceleration...")
    accel = sensor.read_acceleration()
    if accel:
        print(f"Ax: {accel['ax_g']:.3f}g ({accel['ax_ms2']:.2f} m/s²)")
        print(f"Ay: {accel['ay_g']:.3f}g ({accel['ay_ms2']:.2f} m/s²)")
        print(f"Az: {accel['az_g']:.3f}g ({accel['az_ms2']:.2f} m/s²)")
    else:
        print("Failed to read acceleration")
