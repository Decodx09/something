#!/usr/bin/env python3
"""
Run Container Return System on COM8

This script runs the main application configured to listen on COM8.
Use with Null Modem emulator (com0com) to create COM port pairs.

Setup:
1. Install com0com (Null Modem emulator)
2. Create COM port pair: COM7 <-> COM8
3. Run this script (connects to COM8)
4. Run hardware simulator on COM7
"""

import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
env_path = Path('.env')
if env_path.exists():
    load_dotenv(env_path)

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.main import ContainerReturnSystem

def main():
    """Run application using development port configuration"""
    # Get port configuration from environment
    app_port = os.getenv('DEV_UART_PORT_APP', 'COM8')
    simulator_port = os.getenv('DEV_UART_PORT_SIMULATOR', 'COM7')
    baudrate = os.getenv('UART_BAUDRATE', '9600')
    
    print("Container Return System - Development Mode")
    print("=" * 50)
    print(f"Application will connect to: {app_port}")
    print(f"Hardware simulator should use: {simulator_port}")
    print(f"Baudrate: {baudrate}")
    print("Make sure virtual ports are created (com0com/socat)")
    print("Press Ctrl+C to stop")
    print("-" * 50)
    
    # Set development configuration
    os.environ['UART_PORT'] = app_port
    os.environ['UART_BAUDRATE'] = baudrate
    os.environ['DEBUG'] = 'true'
    os.environ['LOG_LEVEL'] = 'DEBUG'
    
    # Create and run application
    app = ContainerReturnSystem()
    return app.run(debug=True)

if __name__ == "__main__":
    sys.exit(main()) 