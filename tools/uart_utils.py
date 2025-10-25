"""
UART Utilities for Hardware Simulator

Helper functions for sending and receiving UART data,
matching the protocol specification.
"""

import serial
import time


def send_data(ser, data):
    """Send data over serial connection"""
    try:
        bytes_written = ser.write(data)
        # Decode frame for debugging
        if len(data) >= 5:
            start = data[0]
            msg_type = data[1] 
            msg_id = data[2]
            length = data[3]
            end = data[-1]
            print(f"📤 Sent {bytes_written} bytes: {data.hex()}")
            print(f"   Frame: start={start:02x} type={msg_type:02x} id={msg_id} len={length} end={end:02x}")
        else:
            print(f"📤 Sent {bytes_written} bytes: {data.hex()}")
        return bytes_written
    except Exception as e:
        print(f"❌ Error sending data: {e}")
        return 0


def receive_data(ser, expected_length=None, timeout=1.0):
    """Receive data from serial connection"""
    try:
        if expected_length:
            data = ser.read(expected_length)
        else:
            # Read what's available
            data = ser.read(ser.in_waiting or 1)
        
        if data:
            print(f"Received {len(data)} bytes: {data.hex()}")
        return data
    except Exception as e:
        print(f"Error receiving data: {e}")
        return b''


def wait_for_data(ser, expected_length=6, timeout=5.0):
    """Wait for specific amount of data with timeout"""
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        if ser.in_waiting >= expected_length:
            return ser.read(expected_length)
        time.sleep(0.1)
    
    # Timeout - return what we have
    return ser.read(ser.in_waiting)


def create_message(msg_type, msg_id, payload=b''):
    """Create UART message with proper framing"""
    frame = bytearray()
    frame.append(ord('{'))  # Start byte 0x7B
    frame.append(msg_type)  # Message type
    frame.append(msg_id)    # Message ID
    frame.append(len(payload))  # Payload length
    if payload:
        frame.extend(payload)
    frame.append(ord('}'))  # End byte 0x7D
    return frame


def create_ack(original_msg_type, original_msg_id):
    """Create ACK message"""
    ack_payload = bytes([original_msg_type, original_msg_id])
    return create_message(0x00, original_msg_id, ack_payload)  # ACK = 0x00 