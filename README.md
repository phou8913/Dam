simulation DTU function  
Fake 的 send_request() 不走网络，而是：

找到对应 device_id 的 FakeDTU 实例

调用 dtu.on_downlink(data_to_send, ...)

让这个 FakeDTU 立刻“生成一条 uplink”并存起来（当作设备回复）
