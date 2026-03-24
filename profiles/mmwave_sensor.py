"""
mmWave Radar Sensor
Parses multi-target detection data from LoRa-connected mmWave radar.
Data format: [Dist_Hi, Dist_Lo, Angle_Hi, Angle_Lo] per target (4 bytes each)
"""

import struct
from typing import Optional, Dict, Any, List


class MMWaveSensor:
    """
    mmWave Radar Sensor Profile.
    Only handles response decoding.
    """

    def decode_targets(self, data) -> Optional[Dict[str, List[float]]]:
        """Decode response bytes/hex into target list."""
        if isinstance(data, str):
            try:
                data = bytes.fromhex(data)
            except ValueError:
                print("Error: Invalid hex string")
                return None

        data_len = len(data)
        if data_len == 0:
            print("Error: Empty data")
            return None

        if data_len % 4 != 0:
            print(f"Warning: Data length {data_len} is not multiple of 4, truncating")
            return None

        num_targets = min(data_len // 4, 5)
        targets = {}

        # Each target uses 4 bytes: distance in mm and angle in centidegrees.
        for i in range(num_targets):
            offset = i * 4
            target_bytes = data[offset:offset + 4]

            if len(target_bytes) < 4:
                break

            try:
                dist_hi = target_bytes[0]
                dist_lo = target_bytes[1]
                distance_raw = (dist_hi << 8) | dist_lo
                distance_m = distance_raw / 1000.0

                angle_hi = target_bytes[2]
                angle_lo = target_bytes[3]
                angle_raw = (angle_hi << 8) | angle_lo

                if angle_raw > 32767:
                    angle_raw = angle_raw - 65536

                angle_deg = angle_raw / 100.0

                if distance_m > 0:
                    target_name = f"target{i + 1}"
                    targets[target_name] = [angle_deg, distance_m]

            except Exception as e:
                print(f"Error parsing target {i + 1}: {e}")
                continue

        return targets if targets else None
