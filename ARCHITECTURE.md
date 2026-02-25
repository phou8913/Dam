# Architecture Design

## 0. Launch Entry Point

- Manual startup:
    - Real server: `python gui.py --mode real`
    - Fake server:
        1. Terminal A: `python fake_server.py`
        2. Terminal B: `python gui.py --mode fake`

## 1. Overall Message Flow

```
GUI (gui.py)
 └─ User clicks "Read Once" or auto polling
    ↓
Sensor Service (sensor_service.py)
 ├─ `read_*()` queues request internally
 ├─ Wait for completion Event internally
 └─ Read latest result from communicator buffer
    ↓
Communicator Worker Thread (communicator.py)
 ├─ Take request from queue
 ├─ Call execute_read_*() from service
    ↓
Sensor Profile (e.g., humidity_temp_sensor.py)
 ├─ Generate command bytes (hex)
 └─ Provide response validator
    ↓
Communicator (communicator.py)
 ├─ Send downlink (rate-limited per DTU)
 ├─ Poll uplinks
 ├─ Match response using validator
 └─ Return raw response
    ↓
Sensor Profile
 └─ Decode response → structured data (dict)
    ↓
Communicator Worker
 ├─ Store result in buffer
 └─ Set Event (signal completion)
    ↓
GUI
 └─ Update UI with `read_*()` returned data
```

**Key Flow**: Request → Queue → Worker → Execute → Buffer → Display

## 2. Function Separation

### GUI (gui.py)
**Responsibilities**:
- User interaction (buttons, auto polling)
- Call sensor_service `read_*()` to get sensor results
- Update UI with returned data

**Does NOT**:
- Handle protocols or raw bytes
- Directly call communicator or profiles

---

### Sensor Service (sensor_service.py)
**Responsibilities**:
- Create Event for each request
- Put requests into queue
- Wait for Event completion and fetch buffered result
- Execute sensor reading workflows (multi-step logic)
- Coordinate between profiles and communicator

**Functions**:
- `read_*()` - Queue request, wait, and return final result dict
- `request_read_*()` - Low-level queue helper returning Event
- `execute_read_*()` - Full read workflow (call profile + communicator)

---

### Communicator (communicator.py)
**Responsibilities**:
- Queue management (request_queue)
- Buffer storage (device + sensor → result)
- Worker thread (process queue asynchronously)
- HTTP communication with LoRa gateway
- Rate limiting (1 sec per DTU)

**Does NOT**:
- Understand sensor protocols
- Decode response bytes

---

### Sensor Profiles
(humidity_temp_sensor.py, tilt_acc_sensor.py, water_level_sensor.py, mmwave_sensor.py)

**Responsibilities**:
- Generate command bytes (hex)
- Validate response (check if it matches request)
- Decode response bytes → dict

**Does NOT**:
- Send network requests
- Manage queues or timing
