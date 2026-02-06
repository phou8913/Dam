"""
Launch GUI with Real LoRa Gateway
Starts the GUI connected to the real LoRa gateway API.
"""

import os
import sys

def main():
    print("=" * 60)
    print("GUI with Real LoRa Gateway Server")
    print("=" * 60)
    print("Connecting to: http://99.10.226.29:4560/api")
    print("=" * 60)
    
    # Ensure environment variable is NOT set (use real server)
    os.environ.pop("USE_FAKE_SERVER", None)
    
    # Import and run GUI
    import gui
    gui.main()

if __name__ == "__main__":
    main()
