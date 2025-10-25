#!/usr/bin/env python3
"""
Utility to detect available HID devices that could be QR scanners.
"""

import os
import sys
from pathlib import Path

try:
    from evdev import InputDevice, list_devices
    HAS_EVDEV = True
except ImportError:
    HAS_EVDEV = False
    print("evdev not available. Install with: sudo apt install python3-evdev")
    sys.exit(1)

def detect_qr_devices():
    """Detect potential QR scanner devices."""
    print("Detecting HID devices that could be QR scanners...")
    print("=" * 50)
    
    # Check for /dev/hidraw* devices
    hidraw_devices = []
    for i in range(10):  # Check hidraw0 to hidraw9
        device_path = f"/dev/hidraw{i}"
        if os.path.exists(device_path):
            hidraw_devices.append(device_path)
    
    if hidraw_devices:
        print("Found /dev/hidraw devices:")
        for device in hidraw_devices:
            try:
                # Try to get some info about the device
                stat = os.stat(device)
                print(f"  {device} (permissions: {oct(stat.st_mode)[-3:]})")
            except Exception as e:
                print(f"  {device} (error: {e})")
    else:
        print("No /dev/hidraw devices found.")
    
    print()
    
    # Check evdev input devices
    print("Checking evdev input devices:")
    devices = [InputDevice(path) for path in list_devices()]
    
    keyboard_devices = []
    for device in devices:
        # Look for devices that have keyboard capabilities
        if device.capabilities().get(1):  # EV_KEY events
            keyboard_devices.append(device)
    
    if keyboard_devices:
        for device in keyboard_devices:
            print(f"  {device.path}: {device.name}")
            print(f"    Vendor: 0x{device.info.vendor:04x}")
            print(f"    Product: 0x{device.info.product:04x}")
            print(f"    Version: {device.info.version}")
            
            # Check if it's likely a scanner (common vendor IDs for scanners)
            scanner_vendors = [0x05e0, 0x0c2e, 0x1a40, 0x0471]  # Common scanner vendors
            if device.info.vendor in scanner_vendors:
                print("    ** Likely QR scanner device **")
            print()
    else:
        print("No keyboard-capable devices found.")
    
    print()
    print("Recommended usage:")
    print("1. Connect your QR scanner")
    print("2. Run this script again to see new devices")
    print("3. Use the device path in your QR scanner configuration")
    print("4. You may need to run with sudo or add your user to the input group:")
    print("   sudo usermod -a -G input $USER")

if __name__ == "__main__":
    detect_qr_devices()