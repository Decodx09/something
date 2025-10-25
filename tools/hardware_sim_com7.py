#!/usr/bin/env python3
"""
Hardware Simulator - Microcontroller Emulator for Raspberry Pi Testing

This simulator acts as the STM32 microcontroller, communicating with the Pi via UART.
It provides comprehensive testing for all 5 sequences with clear logging and responses.

Usage:
1. Configure virtual serial ports (COM7/COM8 or /dev/pts/X)
2. Start this simulator first
3. Start the main Pi application
4. Use interactive commands to test sequences

Commands:
- b: Button press (triggers SEQ1)
- c: Cover detected (triggers SEQ2) 
- n: Container detected (triggers SEQ3)
- qr <code>: Simulate QR scan
- remove_cover: Simulate cover removal
- remove_container: Simulate container removal
- jam_cover: Simulate jammed cover
- jam_container: Simulate jammed container
- clear_jams: Clear all jam states
- status: Show current state
- help: Show commands
- test1, test2, test3: Run full sequence tests
- exit: Quit simulator
"""

import serial
import struct
import time
import threading
import os
from pathlib import Path
from typing import Optional, Dict, Any
from enum import IntEnum

# Load environment variables
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✓ Loaded environment from {env_path}")
except ImportError:
    print("Warning: python-dotenv not available")

# Message Types (matching UART protocol)
class MsgType(IntEnum):
    ACK = 0x00
    GET_SENSOR_STATUS = 0x01
    SENSOR_STATE_CHANGE = 0x02
    RESTART = 0x03
    ACTUATOR_MOVEMENT = 0x04
    LIGHT_MANAGEMENT = 0x05
    BUTTON_PUSHED = 0x06
    ERROR_MSG = 0x07
    DOOR_CONTROL = 0x08

# Constants
START_BYTE = 0x7B  # '{'
END_BYTE = 0x7D    # '}'

class HardwareSimulator:
    """Enhanced hardware simulator for comprehensive sequence testing"""
    
    def __init__(self):
        # Serial configuration
        self.port = '/dev/pts/2'
        self.baudrate = int(os.getenv('UART_BAUDRATE', '9600'))
        self.ser = None
        self.msg_id = 0
        
        # State tracking
        self.cover_detected = False
        self.container_detected = False
        self.cover_jammed = False
        self.container_jammed = False
        
        # Light states
        self.cover_light = "OFF"
        self.container_light = "OFF"
        
        # Actuator states
        self.cover_actuator = "CLOSED"
        self.container_actuator = "CLOSED"
        
        # Door state
        self.doors_locked = True
        
        # Sequence tracking
        self.seq2_completed = False
        self.seq3_completed = False
        
        # Threading
        self.listening = False
        self.listen_thread = None
        
        print(f"🎛️  Hardware Simulator initialized")
        print(f"📡 Port: {self.port} | Baudrate: {self.baudrate}")
    
    def connect(self) -> bool:
        """Connect to serial port"""
        try:
            print(f"🔌 Connecting to {self.port}...")
            self.ser = serial.Serial(self.port, self.baudrate, timeout=1)
            print(f"✅ Connected to {self.port}")
            return True
        except Exception as e:
            print(f"❌ Connection failed: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from serial port"""
        if self.listening:
            self.stop_listening()
        if self.ser:
            self.ser.close()
            self.ser = None
            print("✅ Disconnected")
    
    def get_next_id(self) -> int:
        """Get next message ID (0-99)"""
        self.msg_id = (self.msg_id + 1) % 100
        return self.msg_id
    
    def create_message(self, msg_type: int, payload: bytes = b'') -> bytes:
        """Create UART message frame"""
        msg_id = self.get_next_id()
        frame = bytearray()
        frame.append(START_BYTE)
        frame.append(msg_type)
        frame.append(msg_id)
        frame.append(len(payload))
        frame.extend(payload)
        frame.append(END_BYTE)
        return bytes(frame)
    
    def send_message(self, msg_type: int, payload: bytes = b'') -> bool:
        """Send message to Pi"""
        if not self.ser:
            print("❌ Not connected")
            return False
        
        try:
            frame = self.create_message(msg_type, payload)
            self.ser.write(frame)
            type_name = MsgType(msg_type).name
            print(f"📤 SENT: {type_name} | Payload: {payload.hex()} | Frame: {frame.hex()}")
            return True
        except Exception as e:
            print(f"❌ Send failed: {e}")
            return False
    
    def start_listening(self):
        """Start listening for Pi messages"""
        if not self.listening:
            self.listening = True
            self.listen_thread = threading.Thread(target=self._listen_loop, daemon=True)
            self.listen_thread.start()
            print("👂 Started listening for Pi messages")
    
    def stop_listening(self):
        """Stop listening"""
        if self.listening:
            self.listening = False
            if self.listen_thread:
                self.listen_thread.join(timeout=1)
            print("🔇 Stopped listening")
    
    def _listen_loop(self):
        """Background message listening loop"""
        while self.listening:
            try:
                if self.ser and self.ser.in_waiting > 0:
                    self._process_incoming_data()
                time.sleep(0.1)
            except Exception as e:
                print(f"❌ Listen error: {e}")
    
    def _process_incoming_data(self):
        """Process incoming data from Pi"""
        try:
            data = self.ser.read(self.ser.in_waiting)
            if not data:
                return
            
            # Simple frame extraction
            i = 0
            while i < len(data):
                if data[i] == START_BYTE and i + 4 < len(data):
                    payload_length = data[i + 3]
                    frame_length = 5 + payload_length
                    
                    if i + frame_length <= len(data):
                        frame = data[i:i + frame_length]
                        self._handle_pi_message(frame)
                        i += frame_length
                    else:
                        break
                else:
                    i += 1
        except Exception as e:
            print(f"❌ Data processing error: {e}")
    
    def _handle_pi_message(self, frame: bytes):
        """Handle message from Pi"""
        if len(frame) < 5:
            return
        
        msg_type = frame[1]
        msg_id = frame[2]
        payload_length = frame[3]
        payload = frame[4:4 + payload_length] if payload_length > 0 else b''
        
        try:
            type_name = MsgType(msg_type).name
        except ValueError:
            type_name = f"UNKNOWN(0x{msg_type:02X})"
        
        print(f"📥 RECEIVED: {type_name} | ID: {msg_id} | Payload: {payload.hex()} | Frame: {frame.hex()}")
        
        # Send ACK for all messages except ACK itself
        if msg_type != MsgType.ACK:
            self._send_ack(msg_type, msg_id)
        
        # Handle specific message types
        if msg_type == MsgType.DOOR_CONTROL:
            self._handle_door_control(payload)
        elif msg_type == MsgType.LIGHT_MANAGEMENT:
            self._handle_light_control(payload)
        elif msg_type == MsgType.ACTUATOR_MOVEMENT:
            self._handle_actuator_control(payload)
        elif msg_type == MsgType.GET_SENSOR_STATUS:
            self._handle_sensor_status_request()
        elif msg_type == MsgType.RESTART:
            self._handle_restart()
    
    def _send_ack(self, original_type: int, original_id: int):
        """Send ACK response"""
        ack_payload = struct.pack('<BB', original_type, original_id)
        frame = self.create_message(MsgType.ACK, ack_payload)
        self.ser.write(frame)
        print(f"📤 SENT: ACK for {MsgType(original_type).name} | Payload: {ack_payload.hex()} | Frame: {frame.hex()}")
    
    def _handle_door_control(self, payload: bytes):
        """Handle door control command"""
        if len(payload) >= 1:
            action = payload[0]
            if action == 0x01:  # Unblock
                self.doors_locked = False
                print("🚪 DOORS UNLOCKED")
            elif action == 0x00:  # Block
                self.doors_locked = True
                print("🚪 DOORS LOCKED")
    
    def _handle_light_control(self, payload: bytes):
        """Handle light control command"""
        if len(payload) >= 3:
            position = payload[0]
            color = payload[1]
            light_type = payload[2]
            
            position_name = "CONTAINER" if position == 0x00 else "COVER"
            
            if color == 0x00:  # White
                color_name = "WHITE"
            elif color == 0x01:  # Red
                color_name = "RED"
            elif color == 0x02:  # Green
                color_name = "GREEN"
            elif color == 0x03:  # Disable all
                color_name = "OFF"
            else:
                color_name = f"UNKNOWN({color})"
            
            type_name = "STEADY" if light_type == 0x00 else "BLINKING"
            
            # Update state
            if position == 0x00:  # Container
                self.container_light = color_name if color != 0x03 else "OFF"
            else:  # Cover
                self.cover_light = color_name if color != 0x03 else "OFF"
            
            if color == 0x03:  # Turn off all lights
                self.cover_light = "OFF"
                self.container_light = "OFF"
                print("💡 ALL LIGHTS OFF")
            else:
                print(f"💡 {position_name} LIGHT: {color_name} {type_name}")
    
    def _handle_actuator_control(self, payload: bytes):
        """Handle actuator control command with realistic timing"""
        if len(payload) >= 2:
            actuator_type = payload[0]
            action = payload[1]
            
            actuator_name = "COVER" if actuator_type == 0x00 else "CONTAINER"
            
            if action == 0x00:  # Store (open and close)
                print(f"🔧 {actuator_name} ACTUATOR: STORING...")
                print(f"   ⬆️  Opening {actuator_name.lower()}...")
                if actuator_type == 0x00:
                    self.cover_actuator = "OPEN"
                else:
                    self.container_actuator = "OPEN"
                
                # Simulate opening time
                time.sleep(2)
                
                print(f"   ⬇️  Closing {actuator_name.lower()}...")
                if actuator_type == 0x00:
                    self.cover_actuator = "CLOSED"
                else:
                    self.container_actuator = "CLOSED"
                
                print(f"   ✅ {actuator_name} stored successfully")
                
                # Auto-generate removal events after storage
                threading.Thread(target=self._auto_remove_items, daemon=True).start()
                
            elif action == 0x01:  # Open
                print(f"🔧 {actuator_name} ACTUATOR: OPENING")
                if actuator_type == 0x00:
                    self.cover_actuator = "OPEN"
                else:
                    self.container_actuator = "OPEN"
                    
            elif action == 0x02:  # Close
                print(f"🔧 {actuator_name} ACTUATOR: CLOSING")
                if actuator_type == 0x00:
                    self.cover_actuator = "CLOSED"
                else:
                    self.container_actuator = "CLOSED"
    
    def _auto_remove_items(self):
        """Auto-generate item removal events after storage"""
        time.sleep(3)  # Wait for storage to complete
        
        # Remove cover if detected and not jammed
        if self.cover_detected and not self.cover_jammed:
            print("🔄 Auto-removing cover...")
            self.cover_detected = False
            payload = struct.pack('<BB', 0x00, 0x00)  # Cover sensor, no detection
            self.send_message(MsgType.SENSOR_STATE_CHANGE, payload)
            time.sleep(1)
        
        # Remove container if detected and not jammed
        if self.container_detected and not self.container_jammed:
            print("🔄 Auto-removing container...")
            self.container_detected = False
            payload = struct.pack('<BB', 0x01, 0x00)  # Container sensor, no detection
            self.send_message(MsgType.SENSOR_STATE_CHANGE, payload)
    
    def _handle_sensor_status_request(self):
        """Handle sensor status request"""
        print("📊 Pi requested sensor status")
        # Send cover sensor status
        payload = struct.pack('<BB', 0x00, 0x01 if self.cover_detected else 0x00)
        self.send_message(MsgType.SENSOR_STATE_CHANGE, payload)
        time.sleep(0.1)
        
        # Send container sensor status
        payload = struct.pack('<BB', 0x01, 0x01 if self.container_detected else 0x00)
        self.send_message(MsgType.SENSOR_STATE_CHANGE, payload)
    
    def _handle_restart(self):
        """Handle restart command"""
        print("🔄 Pi requested restart - resetting simulator state")
        self.cover_detected = False
        self.container_detected = False
        self.cover_jammed = False
        self.container_jammed = False
        self.cover_light = "OFF"
        self.container_light = "OFF"
        self.cover_actuator = "CLOSED"
        self.container_actuator = "CLOSED"
        self.doors_locked = True
        self.seq2_completed = False
        self.seq3_completed = False
    
    # User command methods
    def send_button_press(self):
        """Send button press to trigger SEQ1"""
        print("\n🔴 SIMULATING: Button press")
        return self.send_message(MsgType.BUTTON_PUSHED)
    
    def send_cover_detected(self):
        """Send cover detection to trigger SEQ2"""
        print("\n📦 SIMULATING: Cover detected")
        self.cover_detected = True
        payload = struct.pack('<BB', 0x00, 0x01)  # Cover sensor, detection
        return self.send_message(MsgType.SENSOR_STATE_CHANGE, payload)
    
    def send_container_detected(self):
        """Send container detection to trigger SEQ3"""
        print("\n🥤 SIMULATING: Container detected")
        self.container_detected = True
        payload = struct.pack('<BB', 0x01, 0x01)  # Container sensor, detection
        return self.send_message(MsgType.SENSOR_STATE_CHANGE, payload)
    
    def simulate_qr_scan(self, qr_code: str):
        """Simulate QR code scan"""
        print(f"\n📱 SIMULATING: QR scan: {qr_code}")
        try:
            import pynput.keyboard as keyboard
            kb = keyboard.Controller()
            time.sleep(1)
            kb.type(qr_code)
            kb.press(keyboard.Key.enter)
            kb.release(keyboard.Key.enter)
            print(f"✅ QR code sent via keyboard simulation")
        except ImportError:
            print("⚠️  pynput not available - manually type the QR code")
        except Exception as e:
            print(f"❌ QR simulation error: {e}")
    
    def remove_cover(self):
        """Simulate cover removal"""
        if self.cover_detected:
            print("\n📦 SIMULATING: Cover removed")
            self.cover_detected = False
            payload = struct.pack('<BB', 0x00, 0x00)  # Cover sensor, no detection
            return self.send_message(MsgType.SENSOR_STATE_CHANGE, payload)
        else:
            print("⚠️  Cover not detected")
    
    def remove_container(self):
        """Simulate container removal"""
        if self.container_detected:
            print("\n🥤 SIMULATING: Container removed")
            self.container_detected = False
            payload = struct.pack('<BB', 0x01, 0x00)  # Container sensor, no detection
            return self.send_message(MsgType.SENSOR_STATE_CHANGE, payload)
        else:
            print("⚠️  Container not detected")
    
    def jam_cover(self):
        """Simulate jammed cover"""
        print("\n⚠️  SIMULATING: Cover jammed")
        self.cover_jammed = True
        self.cover_detected = True
    
    def jam_container(self):
        """Simulate jammed container"""
        print("\n⚠️  SIMULATING: Container jammed")
        self.container_jammed = True
        self.container_detected = True
    
    def clear_jams(self):
        """Clear all jam states"""
        print("\n✅ CLEARING: All jam states")
        self.cover_jammed = False
        self.container_jammed = False
    
    def show_status(self):
        """Show current simulator state"""
        print("\n" + "="*50)
        print("📊 HARDWARE SIMULATOR STATUS")
        print("="*50)
        print(f"🚪 Doors: {'LOCKED' if self.doors_locked else 'UNLOCKED'}")
        print(f"📦 Cover: {'DETECTED' if self.cover_detected else 'NOT DETECTED'} | {'JAMMED' if self.cover_jammed else 'OK'}")
        print(f"🥤 Container: {'DETECTED' if self.container_detected else 'NOT DETECTED'} | {'JAMMED' if self.container_jammed else 'OK'}")
        print(f"💡 Cover Light: {self.cover_light}")
        print(f"💡 Container Light: {self.container_light}")
        print(f"🔧 Cover Actuator: {self.cover_actuator}")
        print(f"🔧 Container Actuator: {self.container_actuator}")
        print(f"✅ SEQ2 Completed: {self.seq2_completed}")
        print(f"✅ SEQ3 Completed: {self.seq3_completed}")
        print("="*50)
    
    # Test sequences
    def test_sequence_1(self):
        """Test SEQ1: Button Press Activation"""
        print("\n" + "="*60)
        print("🧪 TESTING SEQUENCE 1: Button Press Activation")
        print("="*60)
        
        print("1. Sending button press...")
        self.send_button_press()
        
        print("\n2. Expected Pi responses:")
        print("   - Door unlock command (0x08, action 0x01)")
        print("   - Door lock command (0x08, action 0x00) after 1s")
        print("   - Cover white light (0x05)")
        print("   - Container white light (0x05)")
        print("\n3. Monitoring for 10 seconds...")
        time.sleep(10)
        print("✅ SEQ1 test completed")
    
    def test_sequence_2(self):
        """Test SEQ2: Cover Detection"""
        print("\n" + "="*60)
        print("🧪 TESTING SEQUENCE 2: Cover Detection")
        print("="*60)
        
        print("1. Sending cover detected...")
        self.send_cover_detected()
        
        print("\n2. Expected Pi response:")
        print("   - Cover green light (0x05 for cover, green)")
        print("\n3. Monitoring for 5 seconds...")
        time.sleep(5)
        self.seq2_completed = True
        print("✅ SEQ2 test completed - marked as completed")
    
    def test_sequence_3(self, qr_code=None):
        """Test SEQ3: Container Detection + QR"""
        print("\n" + "="*60)
        print("🧪 TESTING SEQUENCE 3: Container Detection + QR")
        print("="*60)
        
        print("1. Sending container detected...")
        self.send_container_detected()
        
        print("\n2. Waiting 2 seconds for Pi to enter QR mode...")
        time.sleep(2)
        
        # Ask for QR code if not provided
        if qr_code is None:
            print("\n3. Enter QR code to simulate:")
            print("   Valid QR examples:")
            print("   - 1b0b58c9-d377-4439-833e-716f91264b34 (valid)")
            print("   - CONT001 (valid)")
            print("   - INVALID (invalid)")
            qr_code = input("   QR Code: ").strip()
            if not qr_code:
                qr_code = "1b0b58c9-d377-4439-833e-716f91264b34"  # Default
                print(f"   Using default: {qr_code}")
        
        print(f"\n3. Simulating QR scan: {qr_code}")
        self.simulate_qr_scan(qr_code)
        
        print("\n4. Expected Pi response:")
        print("   - Container green light (valid QR)")
        print("   - Container red light (invalid QR)")
        print("\n5. Monitoring for 8 seconds...")
        time.sleep(8)
        self.seq3_completed = True
        print("✅ SEQ3 test completed - marked as completed")
    
    def run_interactive(self):
        """Run interactive command interface"""
        print("\n🎮 INTERACTIVE MODE")
        print("Type 'help' for commands or 'exit' to quit")
        
        while True:
            try:
                cmd = input("\n> ").strip().lower()
                
                if cmd == 'exit':
                    break
                elif cmd == 'help':
                    self._show_help()
                elif cmd == 'b':
                    self.send_button_press()
                elif cmd == 'c':
                    self.send_cover_detected()
                elif cmd == 'n':
                    self.send_container_detected()
                elif cmd.startswith('qr '):
                    qr_code = cmd[3:].strip()
                    if qr_code:
                        self.simulate_qr_scan(qr_code)
                    else:
                        print("❌ Please provide a QR code: qr <code>")
                elif cmd == 'qr':
                    print("📱 Enter QR code to simulate:")
                    print("   Valid examples: 1b0b58c9-d377-4439-833e-716f91264b34, CONT001")
                    print("   Invalid examples: INVALID, BADCODE")
                    qr_code = input("   QR Code: ").strip()
                    if qr_code:
                        self.simulate_qr_scan(qr_code)
                    else:
                        print("❌ No QR code entered")
                elif cmd == 'remove_cover':
                    self.remove_cover()
                elif cmd == 'remove_container':
                    self.remove_container()
                elif cmd == 'jam_cover':
                    self.jam_cover()
                elif cmd == 'jam_container':
                    self.jam_container()
                elif cmd == 'clear_jams':
                    self.clear_jams()
                elif cmd == 'status':
                    self.show_status()
                elif cmd == 'test1':
                    self.test_sequence_1()
                elif cmd == 'test2':
                    self.test_sequence_2()
                elif cmd == 'test3':
                    self.test_sequence_3()
                else:
                    print("❌ Unknown command. Type 'help' for available commands.")
                    
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"❌ Error: {e}")
    
    def _show_startup_commands(self):
        """Show startup command overview"""
        print("\n" + "="*70)
        print("🎮 HARDWARE SIMULATOR COMMANDS")
        print("="*70)
        print("🔴 Basic Commands:")
        print("  b           - Button press (triggers SEQ1)")
        print("  c           - Cover detected (triggers SEQ2)")
        print("  n           - Container detected (triggers SEQ3)")
        print("  qr          - Interactive QR scan (prompts for code)")
        print("  qr <code>   - Direct QR scan with specified code")
        print("")
        print("🔧 Manual Control:")
        print("  remove_cover     - Simulate cover removal")
        print("  remove_container - Simulate container removal")
        print("  jam_cover        - Simulate jammed cover")
        print("  jam_container    - Simulate jammed container")
        print("  clear_jams       - Clear all jam states")
        print("")
        print("🧪 Testing:")
        print("  test1       - Full SEQ1 test (Button → Door → Lights)")
        print("  test2       - Full SEQ2 test (Cover → Green Light)")
        print("  test3       - Full SEQ3 test (Container → QR → Light)")
        print("")
        print("📊 Info:")
        print("  status      - Show current state")
        print("  help        - Show detailed help")
        print("  exit        - Exit simulator")
        print("="*70)
        print("💡 TIP: Start with 'test1' for a complete sequence test!")
    
    def _show_help(self):
        """Show detailed available commands"""
        print("\n📖 DETAILED COMMAND REFERENCE:")
        print("  b                - Send button press (SEQ1)")
        print("  c                - Send cover detected (SEQ2)")
        print("  n                - Send container detected (SEQ3)")
        print("  qr               - Interactive QR scan (prompts for code)")
        print("  qr <code>        - Direct QR scan with specified code")
        print("  remove_cover     - Simulate cover removal")
        print("  remove_container - Simulate container removal")
        print("  jam_cover        - Simulate jammed cover")
        print("  jam_container    - Simulate jammed container")
        print("  clear_jams       - Clear all jam states")
        print("  status           - Show current state")
        print("  test1            - Run SEQ1 test")
        print("  test2            - Run SEQ2 test")
        print("  test3            - Run SEQ3 test")
        print("  help             - Show this help")
        print("  exit             - Exit simulator")


def main():
    """Main simulator function"""
    simulator = HardwareSimulator()
    
    try:
        if not simulator.connect():
            return
        
        simulator.start_listening()
        print("\n🚀 Hardware Simulator ready!")
        print("💡 Start the Pi application, then use commands to test sequences")
        simulator._show_startup_commands()
        
        simulator.run_interactive()
        
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")
    finally:
        simulator.disconnect()


if __name__ == "__main__":
    main()