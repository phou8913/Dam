"""
Launch GUI with Fake HTTP Server
Starts the fake LoRa gateway server in background, then launches the GUI.
"""

import os
import sys
import time
import subprocess
import threading

def start_fake_server():
    """Start fake_server.py in a separate process."""
    print("[Launcher] Starting fake HTTP server...")
    # Start fake server as subprocess
    server_process = subprocess.Popen(
        [sys.executable, "fake_server.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # Wait a bit for server to start
    time.sleep(2)
    
    # Check if server is still running
    if server_process.poll() is None:
        print("[Launcher] Fake server started successfully at http://localhost:5000")
        return server_process
    else:
        print("[Launcher] ERROR: Fake server failed to start!")
        stdout, stderr = server_process.communicate()
        print(f"STDOUT: {stdout}")
        print(f"STDERR: {stderr}")
        sys.exit(1)

def main():
    print("=" * 60)
    print("GUI with Fake LoRa Gateway Server")
    print("=" * 60)
    
    # Set environment variable to use fake server
    os.environ["USE_FAKE_SERVER"] = "1"
    
    # Start fake server
    server_process = start_fake_server()
    
    try:
        # Import and run GUI
        print("[Launcher] Starting GUI...")
        import gui
        gui.main()
    except KeyboardInterrupt:
        print("\n[Launcher] Shutting down...")
    finally:
        # Clean up: terminate fake server
        if server_process and server_process.poll() is None:
            print("[Launcher] Stopping fake server...")
            server_process.terminate()
            server_process.wait(timeout=5)
            print("[Launcher] Fake server stopped.")

if __name__ == "__main__":
    main()
