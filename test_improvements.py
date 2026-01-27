#!/usr/bin/env python3
"""
Test script to verify the improvements:
1. Per-DTU rate limiting and message queue
2. Request-response matching with timeout
"""

import os
import time
import threading

# Enable fake DTU mode
os.environ["USE_FAKE_DTU"] = "1"

from humidity_temp_sensor import HumidityTempSensor
from tilt_acc_sensor import HWT901BSensor
from water_level_sensor import WaterLevelSensor


def test_rate_limiting():
    """
    Test that multiple sensors sending to the same DTU respect rate limiting.
    """
    print("\n" + "="*60)
    print("TEST 1: Per-DTU Rate Limiting")
    print("="*60)
    
    shared_eui = "8695311000942380"
    
    # Create sensors that share the same EUI
    ht_sensor = HumidityTempSensor(dev_eui=shared_eui, min_send_interval_sec=2.0)
    ta_sensor = HWT901BSensor(dev_eui=shared_eui, min_send_interval_sec=2.0)
    wl_sensor = WaterLevelSensor(dev_eui=shared_eui, min_send_interval_sec=2.0)
    
    print(f"\nShared EUI: {shared_eui}")
    print(f"Min interval: 2.0 seconds per DTU")
    print(f"\nStarting simultaneous reads from 3 sensors...")
    
    start_time = time.time()
    
    def read_ht():
        print(f"[HT] Starting read at t={time.time()-start_time:.2f}s")
        data = ht_sensor.read_data(timeout_sec=10.0, poll_interval_sec=0.5)
        elapsed = time.time() - start_time
        if data:
            print(f"[HT] Got response at t={elapsed:.2f}s: T={data['temperature_c']:.2f}°C")
        else:
            print(f"[HT] Failed at t={elapsed:.2f}s")
    
    def read_ta():
        print(f"[TA] Starting read at t={time.time()-start_time:.2f}s")
        data = ta_sensor.read_angles(timeout_sec=10.0, poll_interval_sec=0.5)
        elapsed = time.time() - start_time
        if data:
            print(f"[TA] Got response at t={elapsed:.2f}s: Roll={data['roll']:.2f}°")
        else:
            print(f"[TA] Failed at t={elapsed:.2f}s")
    
    def read_wl():
        print(f"[WL] Starting read at t={time.time()-start_time:.2f}s")
        data = wl_sensor.read_data(timeout_sec=10.0, poll_interval_sec=0.5)
        elapsed = time.time() - start_time
        if data:
            print(f"[WL] Got response at t={elapsed:.2f}s: Level={data['level_m']:.3f}m")
        else:
            print(f"[WL] Failed at t={elapsed:.2f}s")
    
    # Start all reads in parallel
    threads = [
        threading.Thread(target=read_ht, daemon=True),
        threading.Thread(target=read_ta, daemon=True),
        threading.Thread(target=read_wl, daemon=True),
    ]
    
    for t in threads:
        t.start()
    
    for t in threads:
        t.join()
    
    total_time = time.time() - start_time
    print(f"\n✓ All reads completed in {total_time:.2f}s")
    print(f"  (With rate limiting, should be ~6s: 3 sensors × 2s intervals)")


def test_response_matching():
    """
    Test that responses are correctly matched to requests using validators.
    """
    print("\n" + "="*60)
    print("TEST 2: Request-Response Matching with Validators")
    print("="*60)
    
    shared_eui = "8695311000942380"
    
    # Test each sensor's validator
    ht_sensor = HumidityTempSensor(dev_eui=shared_eui)
    ta_sensor = HWT901BSensor(dev_eui=shared_eui)
    wl_sensor = WaterLevelSensor(dev_eui=shared_eui)
    
    print(f"\nTesting validators with valid/invalid responses...")
    
    # Test HT sensor validator
    print("\n1. HumidityTempSensor validator:")
    valid_ht = "01040612dc00d4006cc80000"  # Example valid frame
    print(f"   Valid frame: {ht_sensor._validate_response(valid_ht)}")
    invalid_ht = "50030612dc00d4006cc80000"  # Wrong function code
    print(f"   Invalid (wrong func): {ht_sensor._validate_response(invalid_ht)}")
    short_frame = "0104"  # Too short
    print(f"   Invalid (too short): {ht_sensor._validate_response(short_frame)}")
    
    # Test TA sensor validator
    print("\n2. HWT901BSensor validator:")
    valid_ta = "50030600001122334455"  # Valid frame header
    print(f"   Valid frame: {ta_sensor._validate_angles_response(valid_ta)}")
    invalid_ta = "01040600001122334455"  # Wrong header
    print(f"   Invalid (wrong header): {ta_sensor._validate_angles_response(invalid_ta)}")
    
    # Test WL sensor validator
    print("\n3. WaterLevelSensor validator:")
    valid_wl = "7b0304414b0000c3fe"  # Valid water level frame
    print(f"   Valid frame: {wl_sensor._validate_response(valid_wl)}")
    invalid_wl = "0104044f414240c3fe"  # Wrong slave addr
    print(f"   Invalid (wrong slave): {wl_sensor._validate_response(invalid_wl)}")


def test_single_sensor():
    """
    Test a single sensor to verify it can read data correctly.
    """
    print("\n" + "="*60)
    print("TEST 3: Single Sensor Read (Full Flow)")
    print("="*60)
    
    dev_eui = "8695311000942380"
    
    print(f"\nReading HumidityTempSensor from {dev_eui}...")
    sensor = HumidityTempSensor(dev_eui=dev_eui, min_send_interval_sec=1.0)
    data = sensor.read_data(timeout_sec=10.0, poll_interval_sec=1.0)
    
    if data:
        print(f"✓ Success!")
        print(f"  Temperature: {data['temperature_c']:.2f}°C")
        print(f"  Humidity: {data['humidity_rh']:.2f}%RH")
        print(f"  Dewpoint: {data['dewpoint_c']:.2f}°C")
        print(f"  CRC Valid: {data['crc_valid']}")
    else:
        print(f"✗ Failed to read data")


if __name__ == "__main__":
    print("\n" + "="*60)
    print("IMPROVEMENTS TEST SUITE")
    print("="*60)
    print("Testing: Per-DTU Rate Limiting + Request-Response Matching")
    
    try:
        test_single_sensor()
        test_response_matching()
        test_rate_limiting()
        
        print("\n" + "="*60)
        print("✓ ALL TESTS COMPLETED")
        print("="*60)
        
    except Exception as e:
        print(f"\n✗ Error during testing: {e}")
        import traceback
        traceback.print_exc()
