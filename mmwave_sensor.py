"""
mmWave Radar Sensor
Parses multi-target detection data from LoRa-connected mmWave radar.
Data format: [Dist_Hi, Dist_Lo, Angle_Hi, Angle_Lo] per target (4 bytes each)
"""

import struct
import time
from typing import Optional, Dict, Any, List

import communicator


class MMWaveSensor:
    """
    mmWave Radar Sensor Interface.
    Passively reads target detection data without sending commands.
    """

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

    def parse_mmwave_data(self, data) -> Optional[Dict[str, List[float]]]:
        """
        Parse mmWave radar data containing multiple targets.

        Data format per target (4 bytes):
        - Byte 0: Distance High byte
        - Byte 1: Distance Low byte
        - Byte 2: Angle High byte
        - Byte 3: Angle Low byte

        Args:
            data: Raw bytes or hex string from mmWave sensor

        Returns:
            dict: {"target1": [angle, distance], "target2": [angle, distance], ...}
                  Or None if parsing fails
        """
        if isinstance(data, str):
            try:
                print(data)
                data = bytes.fromhex(data)
            except ValueError:
                print("Error: Invalid hex string")
                return None

        # Each target is 4 bytes, max 5 targets = 20 bytes
        data_len = len(data)
        if data_len == 0:
            print("Error: Empty data")
            return None

        if data_len % 4 != 0:
            print(f"Warning: Data length {data_len} is not multiple of 4, truncating")
            return None

        # Calculate number of targets (max 5)
        num_targets = min(data_len // 4, 5)

        targets = {}

        for i in range(num_targets):
            # Extract 4 bytes for this target
            offset = i * 4
            target_bytes = data[offset:offset + 4]

            if len(target_bytes) < 4:
                break

            try:
                # Parse distance (unsigned 16-bit, big-endian)
                # Assuming distance in cm, convert to meters
                dist_hi = target_bytes[0]
                dist_lo = target_bytes[1]
                distance_raw = (dist_hi << 8) | dist_lo
                distance_m = distance_raw / 1000.0  # Convert cm to meters

                # Parse angle (signed 16-bit, big-endian)
                # Assuming angle in degrees * 10, convert to degrees
                angle_hi = target_bytes[2]
                angle_lo = target_bytes[3]
                angle_raw = (angle_hi << 8) | angle_lo

                # Treat as signed 16-bit
                if angle_raw > 32767:
                    angle_raw = angle_raw - 65536

                angle_deg = angle_raw / 100.0  # Convert to degrees

                # Only include targets with valid distance (> 0)
                if distance_m > 0:
                    target_name = f"target{i + 1}"
                    targets[target_name] = [angle_deg, distance_m]

            except Exception as e:
                print(f"Error parsing target {i + 1}: {e}")
                continue

        return targets if targets else None

    def read_data(
            self,
            max_attempts: int = 1,
            poll_interval: int = 5
    ) -> Optional[Dict[str, List[float]]]:
        """
        Read mmWave radar data from the device.
        Note: mmWave sensor does not require sending commands,
        it continuously broadcasts target data.

        Args:
            max_attempts: Maximum number of polling attempts (default: 1)
            poll_interval: Seconds to wait between polling attempts (default: 5)

        Returns:
            dict: Parsed target data {"target1": [angle, distance], ...}
                  Or None if reading fails
        """
        try:
            token = self._ensure_token()

            # mmWave sensor does not need command sending
            # Just pull the latest uplink data
            for attempt in range(1, max_attempts + 1):
                if attempt > 1:
                    time.sleep(poll_interval)

                status, hex_data = communicator.pull_latest_data(
                    device_id=self.dev_eui,
                    auth_token=token,
                    size=10
                )

                if status == 1 and hex_data:
                    parsed_data = self.parse_mmwave_data(hex_data)
                    return parsed_data

            print(f"No data received from device {self.dev_eui}")
            return None

        except Exception as e:
            print(f"Error reading mmWave data: {e}")
            return None


if __name__ == "__main__":
    DEV_EUI = "8695311001412450"

    sensor = MMWaveSensor(dev_eui=DEV_EUI)
    data = sensor.read_data()

    if data:
        print(f"Detected {len(data)} targets:")
        for target_name, target_data in data.items():
            angle, distance = target_data
            print(f"  {target_name}: {angle:.1f}° @ {distance:.2f}m")
    else:
        print("No targets detected")
