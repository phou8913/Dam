# Message Flow & Function Separation

## 1. Overall Message Flow

```
GUI
 └─(user action / auto polling)
    └─ Sensor Profile
       ├─ generate command bytes (hex)
       └─ response validator
            ↓
        Communicator
        ├─ send downlink (rate-limited, per-DTU)
        ├─ poll uplinks
        ├─ match response using validator
        └─ timeout handling
            ↓
       Sensor Profile
       └─ decode response bytes → structured data
            ↓
GUI
 └─ update UI / visualization
```

Key points

- GUI never handles raw bytes or protocol details.
- Sensor profile never does networking or message scheduling.
- Communicator is the only place that knows how messages are sent, received, queued, and matched.

## 2. Function Separation

### GUI (gui.py)

Responsibilities

- User interaction (manual / auto read)
- UI update and visualization

### Sensor Profiles

(humidity_temp_sensor.py, tilt_acc_sensor.py, water_level_sensor.py, mmwave_sensor.py)

Responsibilities

- Generate command bytes (hex)
- Validate whether a response belongs to a request
- Decode response bytes into structured data (dict)

Does NOT

- Send requests
- Poll uplinks
- Manage queues, timing, or retries

### Communicator (communicator.py)

Responsibilities

- Unified communication layer for both real and fake DTU
- Per-DTU rate limiting (queue + minimum interval)
- Serialized send-and-wait per device (inflight lock)
- Poll uplinks and evaluate responses using validators
- Timeout and old-packet protection

Does NOT

- Decode sensor-specific data

### Backend Selection (config.py, launch scripts)

Responsibilities

- Select real vs fake gateway only by URL
- No logic differences between fake and real DTU

Mechanism

- USE_FAKE_SERVER environment variable
- Different launcher scripts (run_with_fake_server.py, run_with_real_server.py)
