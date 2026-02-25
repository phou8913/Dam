Use fake server  
```python gui.py --mode fake```  

# Layered Message Flow (Bundled Steps)

```text
+-------------------------------+
| [GUI Layer]                   |
| manual read / auto polling    |
+-------------------------------+
                |
                v
+-------------------------------+
| [Service Layer]               |
| request_read_*()              |
| enqueue task with steps       |
+-------------------------------+
                |
                v
+-------------------------------+
| [Communicator Layer]          |
| request_queue + _buffer_worker|
| execute_bundled_read(task)    |
| for step in steps (fail-fast) |
+-------------------------------+
                |
                v
+-------------------------------+
| [Profile Layer]               |
| build command / validate /    |
| decode response               |
+-------------------------------+
                |
                v
+-------------------------------+
| [Communicator Layer]          |
| send_request / send_and_wait  |
| pull_latest_data              |
+-------------------------------+
                |
                v
+-------------------------------+
| LoRa Gateway / Uplink API     |
+-------------------------------+
                |
                v
+-------------------------------+
| [Communicator Layer]          |
| write buffer + set event      |
+-------------------------------+
                |
                v
+-------------------------------+
| [Service Layer]               |
| wait event + get_buffer_data  |
+-------------------------------+
                |
                v
+-------------------------------+
| [GUI Layer]                   |
| update UI                     |
+-------------------------------+
```
