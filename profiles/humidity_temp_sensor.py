import struct
from typing import Optional, Dict, Any, List

from .base import SensorProfile
from .modbus_utils import crc16_modbus


class HumidityTempSensor(SensorProfile):
    """
    Humidity and Temperature Sensor Profile.
    Only handles command byte generation and response decoding.
    """

    SLAVE_ADDR = 0x01

    @classmethod
    def build_request(cls, mode: str = "read") -> bytes:
        if mode != "read":
            raise ValueError("Unsupported mode")

        frame = struct.pack(">BBHH", cls.SLAVE_ADDR, 0x03, 0x0000, 0x0003)
        crc = crc16_modbus(frame)
        return frame + struct.pack("<H", crc)

    def decode_response(self, data, mode: str = "read") -> Optional[Dict[str, Any]]:
        """Decode response bytes/hex into sensor values."""
        if mode != "read":
            raise ValueError("Unsupported mode")

        if isinstance(data, str):
            try:
                data = bytes.fromhex(data)
            except ValueError:
                print("Error: Invalid hex string")
                return None

        try:
            return {
                "temperature_c": struct.unpack(">h", data[3:5])[0] / 100,
                "humidity_rh": struct.unpack(">h", data[5:7])[0] / 100,
                "dewpoint_c": struct.unpack(">h", data[7:9])[0] / 100,
                "raw_hex": data.hex()
            }
        except Exception as e:
            print(f"Error during value parsing: {e}")
            return None

    def build_steps(self) -> List[Dict[str, Any]]:
        ### Build bundled messages
        return [{"mode": "read"}]




    ### Only used in legacy test tools, later they will be deleted in favor of build_steps() and build_request() with mode parameter 
    @classmethod
    def encode_read_command(cls) -> str:
        """Compatibility wrapper for tools that still expect a hex command."""
        return cls.build_request("read").hex()
