"""
Gateway -> DTU connectivity test using HTTP downlink + MQTT ack.

Flow:
1. Authenticate with the LoRa backend.
2. Subscribe to the device ack topic in MQTT.
3. Submit a confirmed downlink with /v1/devices/{device_id}/queue.
4. Wait for the matching ack result event.

Defaults are set from the current MQTTX connection, but every value can be
overridden by command-line arguments or environment variables.
"""

import argparse
import json
import os
import sys
from connectivity_common import (
    MqttTopicListener,
    authenticate,
    build_ack_topic,
    build_reference,
    classify_target,
    get_fake_ack,
    queue_downlink,
)


REAL_BASE_URL = "http://99.10.226.29:4560/api"
DEFAULT_ACCOUNT = os.getenv("LORA_ACCOUNT", "admin")
DEFAULT_PASSWORD = os.getenv("LORA_PASSWORD", "admin")
DEFAULT_DEVICE_ID = os.getenv("DEVICE_ID", "8695311000942380")
DEFAULT_APPLICATION_ID = os.getenv("APPLICATION_ID", "18")
DEFAULT_MQTT_HOST = os.getenv("MQTT_HOST", "99.10.226.29")
DEFAULT_MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
DEFAULT_MQTT_USERNAME = os.getenv("MQTT_USERNAME", "mqtt_user_1")
DEFAULT_MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "mqtt_pass_1")
DEFAULT_MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "mqtt_client_1")
DEFAULT_MQTT_KEEPALIVE = int(os.getenv("MQTT_KEEPALIVE", "60"))
DEFAULT_MQTT_TLS = os.getenv("MQTT_TLS", "0") == "1"


def main() -> int:
    # Parse runtime parameters for HTTP, MQTT, and target device settings.
    parser = argparse.ArgumentParser(description="Test gateway -> DTU connectivity with MQTT ack")
    parser.add_argument("--base-url", default=os.getenv("BASE_URL", REAL_BASE_URL))
    parser.add_argument("--account", default=DEFAULT_ACCOUNT)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--device-id", default=DEFAULT_DEVICE_ID)
    parser.add_argument("--application-id", default=DEFAULT_APPLICATION_ID)
    parser.add_argument("--data-hex", default="01")
    parser.add_argument("--fport", type=int, default=1)
    parser.add_argument("--reference", default="")
    parser.add_argument("--auth-timeout", type=float, default=5.0)
    parser.add_argument("--queue-timeout", type=float, default=10.0)
    parser.add_argument("--ack-timeout", type=float, default=20.0)
    parser.add_argument("--mqtt-host", default=DEFAULT_MQTT_HOST)
    parser.add_argument("--mqtt-port", type=int, default=DEFAULT_MQTT_PORT)
    parser.add_argument("--mqtt-username", default=DEFAULT_MQTT_USERNAME)
    parser.add_argument("--mqtt-password", default=DEFAULT_MQTT_PASSWORD)
    parser.add_argument("--mqtt-client-id", default=DEFAULT_MQTT_CLIENT_ID)
    parser.add_argument("--mqtt-keepalive", type=int, default=DEFAULT_MQTT_KEEPALIVE)
    parser.add_argument("--mqtt-tls", action="store_true", default=DEFAULT_MQTT_TLS)
    args = parser.parse_args()

    # Build the unique downlink reference and the device-specific ack topic.
    reference = args.reference or build_reference("gw-dtu-test")
    ack_topic = build_ack_topic(args.application_id, args.device_id)

    # Authenticate first so the HTTP downlink request can be submitted.
    auth_result = authenticate(args.base_url, args.account, args.password, args.auth_timeout)
    if not auth_result["ok"]:
        print(json.dumps({
            "result": "FAIL",
            "stage": "gateway_dtu",
            "base_url": args.base_url,
            "application_id": args.application_id,
            "device_id": args.device_id,
            "auth": auth_result,
        }, indent=2))
        return 1

    # Start the MQTT listener before sending the downlink to avoid missing a fast ack.
    target = classify_target(args.base_url)
    listener = None
    if target == "fake":
        mqtt_result = {
            "ok": True,
            "stage": "mqtt",
            "timestamp": None,
            "host": "fake-server",
            "port": None,
            "topic": ack_topic,
            "client_id": None,
            "mode": "fake-http-ack",
        }
    else:
        listener = MqttTopicListener(
            host=args.mqtt_host,
            port=args.mqtt_port,
            username=args.mqtt_username,
            password=args.mqtt_password,
            client_id=args.mqtt_client_id,
            keepalive=args.mqtt_keepalive,
            use_tls=args.mqtt_tls,
            topic=ack_topic,
            expected_device_id=args.device_id,
        )

        mqtt_result = listener.start(timeout_sec=5.0)
        if not mqtt_result["ok"]:
            print(json.dumps({
                "result": "FAIL",
                "stage": "gateway_dtu",
                "base_url": args.base_url,
                "application_id": args.application_id,
                "device_id": args.device_id,
                "auth": {
                    "ok": True,
                    "status_code": auth_result.get("status_code"),
                    "elapsed_ms": auth_result.get("elapsed_ms"),
                },
                "mqtt": mqtt_result,
            }, indent=2))
            return 1

    # Submit the confirmed downlink through the same HTTP queue API used by the app.
    queue_result = queue_downlink(
        args.base_url,
        args.device_id,
        auth_result["token"],
        args.data_hex,
        args.fport,
        reference,
        args.queue_timeout,
    )
    if not queue_result["ok"]:
        if listener is not None:
            listener.stop()
        print(json.dumps({
            "result": "FAIL",
            "stage": "gateway_dtu",
            "base_url": args.base_url,
            "application_id": args.application_id,
            "device_id": args.device_id,
            "auth": {
                "ok": True,
                "status_code": auth_result.get("status_code"),
                "elapsed_ms": auth_result.get("elapsed_ms"),
            },
            "mqtt": mqtt_result,
            "queue": queue_result,
        }, indent=2))
        return 1

    # Wait for the ack result event from the subscribed MQTT topic.
    if target == "fake":
        ack_result = get_fake_ack(args.base_url, args.device_id, timeout=args.ack_timeout)
    else:
        ack_result = listener.wait_for_message(
            args.ack_timeout,
            stage="ack",
        )
        if ack_result.get("ok"):
            payload = ack_result.get("payload") or {}
            ack_result["acknowledged"] = payload.get("acknowledged")
        listener.stop()

    # Require both an ack event and acknowledged=true for the current strict PASS result.
    success = ack_result["ok"] and ack_result.get("acknowledged") is True
    output = {
        "result": "PASS" if success else "FAIL",
        "stage": "gateway_dtu",
        "base_url": args.base_url,
        "application_id": args.application_id,
        "device_id": args.device_id,
        "ack_topic": ack_topic,
        "reference": reference,
        "auth": {
            "ok": True,
            "status_code": auth_result.get("status_code"),
            "elapsed_ms": auth_result.get("elapsed_ms"),
        },
        "mqtt": mqtt_result,
        "queue": queue_result,
        "ack": ack_result,
    }
    print(json.dumps(output, indent=2))
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
