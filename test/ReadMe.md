# Connectivity End-to-End Test Cases

This document defines 6 test cases for validating connectivity. The cases cover authentication, queue submission, gateway/DTU acknowledgment, and sensor uplink failure scenarios.

## Architecture Overview

This test framework is organized around three simple entry scripts and one `tools` folder.

- `tools/client_server_check.py`
  - Contains `ClientServerCheck`
  - Formats the `client -> server` segment result from the shared auth and shared queue response

- `tools/gateway_dtu_check.py`
  - Contains `GatewayDtuCheck`
  - Prepares ACK monitoring and then verifies whether the shared downlink request produces a valid ACK result

- `tools/dtu_sensor_check.py`
  - Contains `DtuSensorCheck`
  - Captures the baseline uplink state and then verifies whether a fresh matching uplink appears after the shared request

- `tools/common_check.py`
  - Contains shared helpers like authentication, queue submission, target selection, and shared result formatting

- `connectivity_test.py`
  - Runs the full three-segment connectivity test
  - Reuses one authentication result, one shared request, and one shared reference
  - Stops early when an upstream segment fails
  - Prints the most likely fault location

- `performance_test.py`
  - Runs the connectivity test multiple times
  - Prints a small performance summary

- `button_spam_test.py`
  - Simulates one user clicking the same sensor button many times
  - Helps verify queue behavior

## 0. Base Environment
- **Working directory**: `test`
- **Main command**: `python test/connectivity_test.py`
- **Performance command**: `python test/performance_test.py`
- **Button spam command**: `python test/button_spam_test.py --clicks 10 --sensor ht`
- **Recommended fake base URL**: `http://127.0.0.1:5000/api`
- **Shell**: PowerShell

## 0.1 Shared Request Model

The end-to-end flow sends one shared downlink request for the whole test.

- A single shared `reference` is used for all three segments
- `client_server` uses the shared queue result to build segment 1
- `gateway_dtu` prepares ACK monitoring before the request is sent
- `dtu_sensor` captures the uplink baseline before the request is sent

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

## Performance Test  
<img width="796" height="621" alt="image" src="https://github.com/user-attachments/assets/3b6e53cb-9bfa-4a4c-b8cb-168a0936daeb" />  

Measures mean time, median time, p95, and min/max time for five metrics:  
`total`: End-to-end time  
`auth_times`: Time from sending the auth request to receiving the auth response  
`queue_times`: Time from sending the queue request to receiving the queue response  
`ack_times`: Time from queue submission to receiving the ACK result  
`uplink_poll_times`: Time for the final uplink poll HTTP request itself  

## Multiple fast button clicks Test
<img width="886" height="907" alt="image" src="https://github.com/user-attachments/assets/769e3fd3-0f37-4ecf-91c3-97b2829ffb11" />   

The request queue works because repeated clicks are queued and processed one by one.
