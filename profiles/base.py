from abc import ABC, abstractmethod
from typing import Any, Dict


class SensorProfile(ABC):
    @abstractmethod
    def build_request(self, mode: str = "read") -> bytes:
        pass

    @abstractmethod
    def decode_response(self, data: bytes, mode: str = "read") -> Dict[str, Any]:
        pass
