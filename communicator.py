"""
LoRa API Communicator
Universal interface for LoRa gateway API communication.
Three core functions: authentication, send downlink, and receive uplink.
"""

import requests
import base64
from typing import Optional, Tuple, Any


# API Configuration - Hardcoded for this deployment
BASE_URL = "http://99.10.226.29:4560/api"
ACCOUNT = "admin"
PASSWORD = "admin"


def get_token() -> str:
    """
    Authenticate with the API and retrieve JWT token.

    Returns:
        str: JWT authentication token

    Raises:
        RuntimeError: If authentication fails
        requests.RequestException: If network request fails
    """
    url = f"{BASE_URL}/v1/internal/auth"
    payload = {
        "account": ACCOUNT,
        "password": PASSWORD
    }

    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()

        token = response.json().get("token")
        if not token:
            raise RuntimeError("Authentication successful but no token received")

        return token

    except requests.RequestException as e:
        raise RuntimeError(f"Failed to authenticate: {e}")


def send_request(
    device_id: str,
    data_to_send: str,
    auth_token: str,
    fport: int = 1,
    reference: str = "downlink-cmd"
) -> Tuple[int, Optional[Any]]:
    """
    Send downlink request to a LoRa device.

    Args:
        device_id: Device EUI identifier
        data_to_send: Hex-encoded data string (e.g., "010400000003B00B")
        auth_token: JWT authentication token
        fport: LoRaWAN fPort (default: 1)
        reference: Reference identifier for this command (default: "downlink-cmd")

    Returns:
        tuple: (status, api_response)
            - status: 1 if successful, 0 if failed
            - api_response: API response dict if successful, None if failed
    """
    try:
        url = f"{BASE_URL}/v1/devices/{device_id}/queue"
        headers = {
            "token": auth_token,
            "content-type": "application/json"
        }
        payload = {
            "confirmed": False,
            "mode": "hex",
            "data": data_to_send,
            "fPort": fport,
            "reference": reference
        }

        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()

        return (1, response.json())

    except Exception as e:
        print(f"Error sending request: {e}")
        return (0, None)


def pull_latest_data(
    device_id: str,
    auth_token: str,
    size: int = 10
) -> Tuple[int, Optional[str]]:
    """
    Pull latest uplink data from a LoRa device.
    Searches recent uplinks for valid application data.

    Args:
        device_id: Device EUI identifier
        auth_token: JWT authentication token
        size: Number of recent uplinks to check (default: 10)

    Returns:
        tuple: (status, hex_data)
            - status: 1 if valid data found, 0 if no valid data
            - hex_data: Hex string of payload if found, None if not found
    """
    try:
        url = f"{BASE_URL}/v1/uplink-storage/devices/{device_id}/uplink"
        headers = {"token": auth_token}
        params = {"size": size, "page": 1}

        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()

        uplinks = response.json().get("result", [])

        # Find first uplink with valid application data (fPort > 0 and data present)
        for uplink in uplinks:
            raw_b64 = uplink.get("data")
            fport = uplink.get("fPort", 0)

            if raw_b64 and fport > 0:
                try:
                    raw_bytes = base64.b64decode(raw_b64)
                    hex_data = raw_bytes.hex()
                    return (1, hex_data)
                except Exception as e:
                    print(f"Warning: Failed to decode uplink payload: {e}")
                    continue

        # No valid data found
        return (0, None)

    except Exception as e:
        print(f"Error pulling data: {e}")
        return (0, None)


# ============ Example Usage ============

if __name__ == "__main__":
    print("=== LoRa API Communicator Example ===\n")

    # Example device EUI (replace with your actual device)
    DEV_EUI = "8695311000931640"

    try:
        # Step 1: Get authentication token
        print("1. Authenticating...")
        token = get_token()
        print(f"   Token obtained: {token[:20]}...\n")

        # Step 2: Send downlink command
        print("2. Sending downlink command...")
        status, response = send_request(
            device_id=DEV_EUI,
            data_to_send="010400000003B00B",
            auth_token=token
        )

        if status == 1:
            print(f"   Success! Response: {response}")
        else:
            print(f"   Failed to send command")
        print()

        # Step 3: Pull latest uplink data
        print("3. Pulling latest uplink data...")
        status, raw_data = pull_latest_data(
            device_id=DEV_EUI,
            auth_token=token,
            size=10
        )

        if status == 1 and raw_data:
            print(f"   Data found!")
            print(f"   Hex: {raw_data}")
            print(f"   Length: {len(raw_data)} bytes")
        else:
            print(f"   No valid data found")

    except Exception as e:
        print(f"Error: {e}")
