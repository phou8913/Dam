# Connectivity End-to-End Test Cases

This document defines 6 test cases for validating end-to-end connectivity. The cases cover authentication, queue submission, gateway/DTU acknowledgment, and sensor uplink failure scenarios.

## Architecture Overview

This test framework is organized around three check classes and one main orchestrator script.

- `client_server_check.py`
  - Contains `ClientServerCheck`
  - Verifies the `client -> server` segment by checking authentication and queue submission

- `gateway_dtu_check.py`
  - Contains `GatewayDtuCheck`
  - Verifies the `gateway -> dtu` segment by checking whether a downlink request can produce a valid ACK result

- `dtu_sensor_check.py`
  - Contains `DtuSensorCheck`
  - Verifies the `dtu -> sensor` segment by checking whether a fresh uplink is observed after the request

- `connectivity_end_to_end.py`
  - Acts as the main test entrypoint
  - Reuses one authentication result and one shared request when possible
  - Runs the three segments in order
  - Stops early when an upstream segment fails
  - Produces a summarized result that indicates the most likely fault location

## 0. Base Environment
- **Main command**: `python .\test\connectivity_end_to_end.py`
- **Shell**: PowerShell

---

## 1. Detailed Test Cases

### Case 1: Full Chain Healthy
- **Scenario**: Verify the normal flow when all components are working correctly.
- **Environment variables**:
  ```powershell
  $env:FAKE_AUTH_OK="1"
  $env:FAKE_QUEUE_OK="1"
  $env:FAKE_ACK_ENABLED="1"
  $env:FAKE_ACKNOWLEDGED="1"
  $env:FAKE_UPLINK_ENABLED="1"
  Remove-Item Env:FAKE_SENSOR_MATCH -ErrorAction Ignore
  ```
- **Expected result**:
  - `client_server` = **PASS**
  - `gateway_dtu` = **PASS**
  - `dtu_sensor` = **PASS**
  - `end_to_end` = **PASS**
<img width="1132" height="1037" alt="image" src="https://github.com/user-attachments/assets/7dac9511-f6f8-4e8a-a3c8-6ca9c5756ae7" />

### Case 2: Client -> Server Authentication Failure
- **Scenario**: Simulate a permission or token failure.
- **Environment variables**:
  ```powershell
  $env:FAKE_AUTH_OK="0"
  $env:FAKE_QUEUE_OK="1"
  $env:FAKE_ACK_ENABLED="1"
  $env:FAKE_ACKNOWLEDGED="1"
  $env:FAKE_UPLINK_ENABLED="1"
  ```
- **Expected result**:
  - Segment 1: **FAIL**
  - Segments 2 and 3: **NOT_RUN**
  - **Fault location**: `client -> server`
<img width="1070" height="803" alt="image" src="https://github.com/user-attachments/assets/6c92265e-a55c-48b5-b28b-99bfed1eac6b" />



### Case 3: Client -> Server Queue Failure
- **Scenario**: Authentication succeeds, but the message cannot enter the backend queue.
- **Environment variables**:
  ```powershell
  $env:FAKE_AUTH_OK="1"
  $env:FAKE_QUEUE_OK="0"
  $env:FAKE_ACK_ENABLED="1"
  $env:FAKE_ACKNOWLEDGED="1"
  $env:FAKE_UPLINK_ENABLED="1"
  ```
- **Expected result**:
  - Segment 1: **FAIL**
  - Segments 2 and 3: **NOT_RUN**
  - **Fault location**: `client -> server`
<img width="1087" height="803" alt="image" src="https://github.com/user-attachments/assets/cc94c65f-7ced-4e76-b01f-92f8de833a84" />


### Case 4: Gateway -> DTU Without ACK
- **Scenario**: Simulate a downlink with no response from the DTU.
- **Environment variables**:
  ```powershell
  $env:FAKE_AUTH_OK="1"
  $env:FAKE_QUEUE_OK="1"
  $env:FAKE_ACK_ENABLED="0"
  $env:FAKE_ACKNOWLEDGED="1"
  $env:FAKE_UPLINK_ENABLED="1"
  ```
- **Expected result**:
  - Segment 1: **PASS**
  - Segment 2: **FAIL**
  - Segment 3: **NOT_RUN**
  - **Fault location**: `server/platform -> gateway -> dtu`
<img width="1084" height="930" alt="image" src="https://github.com/user-attachments/assets/79c237f4-deb6-4fc1-a9b8-7f272bf9cece" />


### Case 5: Gateway -> DTU ACK Exists but Is Not Acknowledged
- **Scenario**: The DTU returns an ACK message, but the request is not accepted or not successfully acknowledged.
- **Environment variables**:
  ```powershell
  $env:FAKE_AUTH_OK="1"
  $env:FAKE_QUEUE_OK="1"
  $env:FAKE_ACK_ENABLED="1"
  $env:FAKE_ACKNOWLEDGED="0"
  $env:FAKE_UPLINK_ENABLED="1"
  ```
- **Expected result**:
  - Segment 1: **PASS**
  - Segment 2: **FAIL**
  - Segment 3: **NOT_RUN**
  - **Fault location**: `server/platform -> gateway -> dtu`
<img width="1079" height="931" alt="image" src="https://github.com/user-attachments/assets/a3e3df3a-3b22-43c7-9e02-356461abaecb" />


### Case 6: DTU -> Sensor Without Uplink
- **Scenario**: The DTU receives the command successfully, but the sensor does not report any data.
- **Environment variables**:
  ```powershell
  $env:FAKE_AUTH_OK="1"
  $env:FAKE_QUEUE_OK="1"
  $env:FAKE_ACK_ENABLED="1"
  $env:FAKE_ACKNOWLEDGED="1"
  $env:FAKE_UPLINK_ENABLED="0"
  ```
- **Expected result**:
  - Segment 1: **PASS**
  - Segment 2: **PASS**
  - Segment 3: **FAIL**
  - **Fault location**: `dtu -> sensor`
<img width="1092" height="1040" alt="image" src="https://github.com/user-attachments/assets/6d332f24-2795-48c0-ad8b-d4d3a790277e" />



