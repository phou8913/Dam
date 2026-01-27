# 快速参考：Per-DTU Rate Limiting & Request-Response Matching

## 改进前后对比

### 改进前（存在的问题）
```python
# 问题1: 无 Rate Limiting - 多个传感器并发打爆DTU
sensor1.read_data(...)  # 线程A: 发送给 DTU
sensor2.read_data(...)  # 线程B: 同时发送给同一DTU
sensor3.read_data(...)  # 线程C: 同时发送给同一DTU
# 结果: DTU 接收到密集的消息，可能丢包或不稳定

# 问题2: 无响应匹配 - "拉最新"容易串台
status, data = communicator.send_request(...)
for attempt in range(12):
    time.sleep(5)
    status, hex_data = communicator.pull_latest_data(...)  # 拉最新一条
    if status:
        return parse(hex_data)  # 可能是旧数据、延迟包、或别的传感器的响应
```

### 改进后（解决方案）
```python
# 方案1: Per-DTU Rate Limiting 自动生效
sensor1 = HumidityTempSensor(eui, min_send_interval_sec=1.0)
sensor2 = HWT901BSensor(eui, min_send_interval_sec=1.0)
sensor3 = WaterLevelSensor(eui, min_send_interval_sec=1.0)

# 即使在多线程中调用，同一DTU的请求也会排队、尊重间隔
t1 = Thread(target=sensor1.read_data)  # 时刻 0.0s
t2 = Thread(target=sensor2.read_data)  # 时刻 0.0s  
t3 = Thread(target=sensor3.read_data)  # 时刻 0.0s
t1.start(); t2.start(); t3.start()
t1.join(); t2.join(); t3.join()
# 实际执行: t1@0.0s, t2@1.0s, t3@2.0s

# 方案2: 请求-响应绑定 + Timeout
status, hex_data = communicator.send_and_wait(
    device_id=eui,
    data_to_send=cmd,
    auth_token=token,
    response_validator=sensor._validate_response,  # 强匹配
    timeout_sec=30.0,  # 超时自动失败（不串台）
    ...
)
# 保证: hex_data 来自本次请求 且 符合预期格式
```

---

## 核心 API

### 1. send_request() - 带 Rate Limiting
```python
from communicator import send_request, get_token

token = get_token()
status, response = send_request(
    device_id="8695311000942380",
    data_to_send="010400000003B00B",
    auth_token=token,
    fport=1,
    reference="humidity-read",
    min_interval_sec=1.0  # ← 新参数：该DTU最小间隔
)
if status == 1:
    print("✓ 消息已排队并发送")
else:
    print("✗ 发送失败")
```

**特点**:
- 自动为每个 `device_id` 创建队列
- 同一DTU的请求会尊重 `min_interval_sec` 间隔
- 返回格式保持兼容

---

### 2. send_and_wait() - 请求+响应等待
```python
from communicator import send_and_wait, get_token

def my_validator(hex_data: str) -> bool:
    """返回 True = 这是我的响应"""
    try:
        data = bytes.fromhex(hex_data)
        return data[0] == 0x01 and data[1] == 0x04  # 检查Modbus函数码
    except:
        return False

status, hex_response = send_and_wait(
    device_id="8695311000942380",
    data_to_send="010400000003B00B",
    auth_token=token,
    response_validator=my_validator,  # ← 强匹配函数
    timeout_sec=30.0,  # 超时等待时间
    fport=1,
    reference="read",
    min_interval_sec=1.0,
    poll_interval_sec=1.0  # 轮询间隔
)

if status == 1:
    print(f"✓ 收到匹配的响应: {hex_response}")
else:
    print(f"✗ 超时或没有匹配响应")
```

**特点**:
- 内部调用 `send_request()` (自动 rate limiting)
- 循环检查 uplinks，只接受 `ts > sent_at` 且通过 validator
- timeout 后自动返回失败（不会返回旧数据）

---

### 3. pull_latest_uplinks() - 获取带时间戳的列表
```python
from communicator import pull_latest_uplinks, get_token

status, uplinks = pull_latest_uplinks(
    device_id="8695311000942380",
    auth_token=token,
    size=10  # 拉最近10条
)

if status == 1:
    for uplink in uplinks:
        print(f"时刻 {uplink['ts']}: {uplink['hex']} (fport={uplink['fport']})")
else:
    print("无新数据")
```

**返回格式**:
```python
[
    {
        "ts": 1705039200.123,     # Unix 时间戳
        "hex": "01040612dc...",   # 数据
        "fport": 1,               # LoRaWAN fPort
        "raw": {...}              # 原始API响应（real后端）
    },
    ...
]
```

---

## 传感器使用方式

### HumidityTempSensor
```python
sensor = HumidityTempSensor(
    dev_eui="8695311000942380",
    min_send_interval_sec=1.0  # 新参数
)

# 读取数据（使用新参数）
data = sensor.read_data(
    timeout_sec=30.0,        # 新参数：超时时间
    poll_interval_sec=1.0    # 新参数：轮询间隔
)

if data:
    print(f"温度: {data['temperature_c']:.2f}°C")
    print(f"湿度: {data['humidity_rh']:.2f}%RH")
    print(f"CRC: {data['crc_valid']}")
```

### HWT901BSensor
```python
sensor = HWT901BSensor(
    dev_eui="8695311000942380",
    min_send_interval_sec=1.0
)

# 读角度（使用新参数）
angles = sensor.read_angles(
    timeout_sec=30.0,
    poll_interval_sec=1.0,
    auto_unlock=True
)

# 读加速度
accel = sensor.read_acceleration(
    timeout_sec=30.0,
    poll_interval_sec=1.0,
    auto_unlock=False  # 第二次读取不需要unlock
)
```

### WaterLevelSensor
```python
sensor = WaterLevelSensor(
    dev_eui="8695311000942380",
    min_send_interval_sec=1.0
)

data = sensor.read_data(
    timeout_sec=30.0,
    poll_interval_sec=1.0
)

if data:
    print(f"水位: {data['level_m']:.3f}m")
    print(f"CRC: {data['crc_valid']}")
```

---

## 内部工作原理

### Per-DTU Queue（DTUQueue 类）
```
Thread A: send_and_wait(DTU_X)
  ↓ 入队 → [Queue for DTU_X]
           ↓
         Worker Thread (for DTU_X)
           ├─ 检查时间间隔
           ├─ 如果不足 min_interval 就 sleep
           └─ 执行发送 → 返回结果给 Thread A

Thread B: send_and_wait(DTU_X)  (同时刻)
  ↓ 入队 → [Queue for DTU_X]
           ↓
         等待 Thread A 执行完
           ├─ 检查时间间隔
           ├─ sleep(min_interval - elapsed)
           └─ 执行发送 → 返回结果给 Thread B

Thread C: send_and_wait(DTU_Y)  (不同DTU)
  ↓ 入队 → [Queue for DTU_Y]
           ↓
         Worker Thread (for DTU_Y) - 独立运行
           └─ 无需等待其他DTU
```

### Request-Response Matching
```
发送时刻 t0:
  send_and_wait() 记录 sent_at = t0
                   开始轮询 uplinks
  
轮询循环 (timeout=30s):
  ├─ 拉取 uplinks (ts≥t0)
  ├─ 对每条 uplink:
  │  ├─ 检查 ts ≥ sent_at? (排除旧包)
  │  └─ 调用 validator(hex)? (协议匹配)
  │     └─ 都通过 → 返回这条 ✓
  │     └─ validator失败 → 继续找下一条
  ├─ 如果找到 → 返回 (status=1)
  ├─ 如果超时 → 返回 (status=0) 防止假成功
  └─ 如果轮询间隔内无新数据 → sleep(poll_interval) 后重试
```

---

## 故障排查

### 问题1: "No response received" Timeout

**可能原因**:
1. DTU 未响应（检查硬件/网络）
2. Validator 过于严格（false negative）
3. 超时设置太短

**解决**:
```python
# 增加超时，调整轮询间隔
data = sensor.read_data(
    timeout_sec=60.0,           # 增加到 60 秒
    poll_interval_sec=2.0       # 增加轮询间隔减少API调用
)

# 或检查 validator 逻辑
print(f"Validator test: {sensor._validate_response(test_hex)}")
```

### 问题2: 多传感器共享DTU时串台

**症状**: 某传感器读到错误的温度/加速度值

**原因**: 未启用新的 send_and_wait()

**解决**: 确保使用的是最新的 sensor 版本
```python
# 检查是否使用了 min_send_interval_sec 参数
sensor = HumidityTempSensor(eui, min_send_interval_sec=1.0)  ✓
sensor = HumidityTempSensor(eui)  # ✗ 旧方式
```

### 问题3: send_request() 返回 (0, None)

**可能原因**:
1. 身份验证失败
2. 该DTU的消息队列已满
3. 网络错误

**解决**:
```python
token = get_token()  # 重新获取token
status, response = send_request(
    device_id=eui,
    data_to_send=cmd,
    auth_token=token,
    min_interval_sec=1.0
)
print(f"Status: {status}, Response: {response}")
```

---

## 环境变量

### 启用 Fake DTU（调试）
```bash
export USE_FAKE_DTU=1
python gui.py
```

不需要真实硬件也能测试 Rate Limiting 和 Request-Response 匹配逻辑。

### 禁用（生产环境）
```bash
unset USE_FAKE_DTU
python gui.py
# 或
USE_FAKE_DTU=0 python gui.py
```

---

## 性能建议

| 参数 | 推荐值 | 说明 |
|------|-------|------|
| `min_interval_sec` | 1.0~2.0 | 根据DTU规格，通常 1-2秒 |
| `timeout_sec` | 30.0 | 足以覆盖网络延迟 |
| `poll_interval_sec` | 1.0~2.0 | 轮询间隔，过短会浪费API配额 |
| 共享DTU数 | ≤3 | 超过会导致总耗时线性增加 |

---

**版本**: 2.0 (2026-01-26)  
**完成度**: ✓ 所有核心功能已实现并测试
