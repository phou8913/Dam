"""
Configuration for LoRa Gateway API
Switch between real and fake gateway by changing BASE_URL
"""

import os

# Determine which gateway to use
USE_FAKE_SERVER = os.getenv("USE_FAKE_SERVER") == "1"

if USE_FAKE_SERVER:
    # Fake HTTP server (run fake_server.py first)
    BASE_URL = "http://localhost:5000/api"
    print("[CONFIG] Using FAKE HTTP server at localhost:5000")
else:
    # Real LoRa gateway
    BASE_URL = "http://99.10.226.29:4560/api"
    print("[CONFIG] Using REAL LoRa gateway")

# Authentication credentials
ACCOUNT = "admin"
PASSWORD = "admin"
