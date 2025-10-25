"""
UART Communication System

Focused on essential functions: encode messages, decode messages, validate messages.
Works with real COM ports for hardware communication.

SPECIFICATION COMPLIANCE:
This implementation matches the JSON specification exactly:

Message Types:
- ACK (0x00): Micro and Pi, payload length 2, format [type, id] 
- Get sensor Status (0x01): Pi, payload length 0 - Micro replies with 0x02 for each sensor
- Sensor state change (0x02): Micro, payload length 2, format [sensor_type, new_status]
  * sensor_type: 0x00=cover sensor, 0x01=container sensor  
  * new_status: 0x00=no detection, 0x01=detection
- Restart (0x03): Pi, payload length 0 - Ask micro to restart
- Actuators movement (0x04): Pi, payload length 2, format [actuator_type, action]
- Light management (0x05): Pi, payload length 3, format [position, light_color, light_type]  
- Button pushed (0x06): Micro, payload length 0
- Error Msg (0x07): Micro, payload length up to 1000

Note: QR scanning is handled via USB connection to Raspberry Pi, not through UART.

Frame Structure:
- Start Byte: 0x7B ('{') 
- Type: Message type (0x00-0x08)
- ID: Message ID/count (0-99) 
- Payload Length: 0-255 bytes
- Payload: Message data according to type specification
- End Byte: 0x7D ('}')
"""

import struct
from datetime import datetime, timezone

import serial
import logging
import time
from typing import Optional, List, Any, Dict, Callable
from enum import IntEnum
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class MessageType(IntEnum):
    """UART message types matching specification"""
    ACK = 0x00
    GET_SENSOR_STATUS = 0x01
    SENSOR_STATE_CHANGE = 0x02
    RESTART = 0x03
    ACTUATOR_MOVEMENT = 0x04
    LIGHT_MANAGEMENT = 0x05
    BUTTON_PUSHED = 0x06
    ERROR_MSG = 0x07
    DOOR_CONTROL = 0x08


class ActuatorType(IntEnum):
    """Actuator types for UART commands"""
    COVER = 0x00  # Cover actuator
    CONTAINER = 0x01  # Container actuator


class ActuatorAction(IntEnum):
    """Actuator actions"""
    STORE = 0x00  # Store (open and close)
    OPEN = 0x01  # Open
    CLOSE = 0x02  # Close


class LightPosition(IntEnum):
    """Light positions for UART commands"""
    CONTAINER = 0x00  # Container position
    COVER = 0x01  # Cover position


class LightColor(IntEnum):
    """Light colors/operations"""
    WHITE_ON = 0x00  # White Turn On
    RED_ON = 0x01  # Red Turn On
    GREEN_ON = 0x02  # Green Turn On
    DISABLE_ALL = 0x03  # Disable all lights


class LightType(IntEnum):
    """Light types"""
    STEADY = 0x00  # Steady
    BLINKING = 0x01  # Blinking


class SensorType(IntEnum):
    """Sensor types from UART SENSOR_STATE_CHANGE messages"""
    COVER = 0x00  # Cover sensor
    CONTAINER = 0x01  # Container sensor


class SensorStatus(IntEnum):
    """Sensor status values"""
    NO_DETECTION = 0x00  # No detection
    DETECTION = 0x01  # Detection


class DoorAction(IntEnum):
    """Door control actions"""
    BLOCK = 0x00  # Block doors
    UNBLOCK = 0x01  # Unblock doors


@dataclass
class UARTMessage:
    """Simple UART message"""
    msg_type: MessageType
    msg_id: int
    payload: bytes = b''

    @property
    def payload_length(self) -> int:
        return len(self.payload)


class UARTProtocol:
    START_BYTE = 0x7B  # '{' character
    END_BYTE = 0x7D  # '}' character

    @staticmethod
    def encode_message(message: UARTMessage) -> bytes:
        """
        Encode message to binary frame.
        Frame: START_BYTE + TYPE + ID + LENGTH + PAYLOAD + END_BYTE
        """
        if not UARTProtocol.validate_message(message):
            raise ValueError(f"Invalid message: {message}")

        frame = bytearray()
        frame.append(UARTProtocol.START_BYTE)
        frame.append(message.msg_type)
        frame.append(message.msg_id)
        frame.append(message.payload_length)

        if message.payload:
            frame.extend(message.payload)

        frame.append(UARTProtocol.END_BYTE)

        return bytes(frame)

    @staticmethod
    def decode_frame(frame: bytes) -> Optional[UARTMessage]:
        """Decode binary frame to message"""
        if not UARTProtocol.validate_frame(frame):
            return None

        try:
            msg_type = MessageType(frame[1])
            msg_id = frame[2]
            payload_length = frame[3]
            payload = frame[4:4 + payload_length] if payload_length > 0 else b''

            return UARTMessage(msg_type, msg_id, payload)
        except (ValueError, IndexError) as e:
            logger.error(f"Decode error: {e}")
            return None

    @staticmethod
    def validate_frame(frame: bytes) -> bool:
        """Validate binary frame"""
        if len(frame) < 5:  # Minimum: START + TYPE + ID + LENGTH + END
            return False

        # Check start byte
        if frame[0] != UARTProtocol.START_BYTE:
            return False

        # Check end byte
        if frame[-1] != UARTProtocol.END_BYTE:
            return False

        # Check frame length matches payload length + overhead
        payload_length = frame[3]
        expected_length = 5 + payload_length  # START + TYPE + ID + LENGTH + PAYLOAD + END
        if len(frame) != expected_length:
            return False

        return True

    @staticmethod
    def validate_message(message: UARTMessage) -> bool:
        """Validate message"""
        if not (0 <= message.msg_id <= 99):
            return False

        if message.payload_length > 255:
            return False

        try:
            MessageType(message.msg_type)
        except ValueError:
            return False

        return True

    @staticmethod
    def create_ack(original_msg: UARTMessage) -> UARTMessage:
        """Create ACK message with payload [type, id] format"""
        ack_payload = struct.pack('<BB', original_msg.msg_type, original_msg.msg_id)
        # ACK message gets its own unique ID, not the original message ID
        ack_id = 0  # ACK messages can use ID 0 or generate new ID
        return UARTMessage(MessageType.ACK, ack_id, ack_payload)


class UART:
    """
    Pi-side UART communication manager for real COM ports.
    
    This class handles UART communication from the Pi's perspective and
    manages sequences based on incoming messages.
    
    SENDS (Pi to Micro):
    - ACK (0x00): Acknowledgment responses
    - Get sensor Status (0x01): Request sensor status from micro
    - Restart (0x03): Tell micro to restart
    - Actuators movement (0x04): Control actuators (cover, container, conveyor)
    - Light management (0x05): Control lights (position, color)
    
    RECEIVES (Micro to Pi):
    - ACK (0x00): Acknowledgment from micro
    - Sensor state change (0x02): Sensor status updates from micro
    - Button pushed (0x06): Button press events from micro
    - Error Msg (0x07): Error messages from micro
    """

    def __init__(self, port: str = "COM8", baudrate: int = 9600, db_manager=None, debug_mode=False):
        self.port = port
        self.baudrate = baudrate
        self.serial_connection: Optional[serial.Serial] = None
        self.message_id_counter = 0
        self.db_manager = db_manager
        self.debug_mode = debug_mode
        self.api_service = None  # Will be set by main application
        self.audit_logger = None  # Will be set by main application
        self.qr_processor = None  # Will be set by main application

        # Sensor state tracking
        self.sensor_states = {
            SensorType.COVER: False,
            SensorType.CONTAINER: False
        }

        # Message processing callbacks
        self.message_handlers = {
            MessageType.BUTTON_PUSHED: self._handle_button_press,
            MessageType.SENSOR_STATE_CHANGE: self._handle_sensor_change,
            MessageType.ERROR_MSG: self._handle_error_message,
            MessageType.ACK: self._handle_ack
        }

        # ACK waiting mechanism
        self._last_ack_id = None
        self._waiting_for_ack = False

        # QR validation state
        self._waiting_for_qr = False
        self._qr_timeout_start = None
        self._container_qr_code = None

        # Sequence completion tracking
        self._seq2_completed = False
        self._seq2_completion_time = None
        self._seq3_completed = False
        self._seq3_completion_time = None
        self._seq1_lights_active = False
        self._seq1_activation_time = None

        # Sequence execution guards (prevent re-entry)
        self._seq4_in_progress = False

        # Device status
        self._device_inactive_callback = None

        logger.info(f"UART initialized for port {port}")

    def set_api_service(self, api_service) -> None:
        """Set the API service for server validation"""
        self.api_service = api_service

    def set_audit_logger(self, audit_logger) -> None:
        """Set the audit logger for logging validation decisions"""
        self.audit_logger = audit_logger

    def set_device_inactive_callback(self, callback) -> None:
        """Set callback to check if device is inactive"""
        self._device_inactive_callback = callback

    def _is_device_inactive(self) -> bool:
        """Check if device is currently inactive"""
        if self._device_inactive_callback:
            try:
                return self._device_inactive_callback()
            except Exception as e:
                logger.error(f"Error checking device inactive status: {e}")
                return False
        return False

    def connect(self) -> bool:
        """Connect to COM port"""
        try:
            self.serial_connection = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=1.0
            )
            logger.info(f"Connected to {self.port} at {self.baudrate}")
            return True
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    def disconnect(self) -> None:
        """Disconnect from COM port"""
        if self.serial_connection:
            self.serial_connection.close()
            self.serial_connection = None
            logger.info("UART disconnected")

    def get_next_message_id(self) -> int:
        """Get next message ID (0-99)"""
        self.message_id_counter = (self.message_id_counter + 1) % 100
        return self.message_id_counter

    def send_message(self, msg_type: MessageType, payload: bytes = b'') -> bool:
        """Send message"""
        if not self.serial_connection:
            logger.error("UART not connected")
            return False

        try:
            msg_id = self.get_next_message_id()
            message = UARTMessage(msg_type, msg_id, payload)
            frame = UARTProtocol.encode_message(message)

            bytes_written = self.serial_connection.write(frame)
            if bytes_written is not None and bytes_written > 0:
                logger.debug(f"Sent: {msg_type.name} (ID: {msg_id}) - {bytes_written} bytes")
                return True
            else:
                logger.error(f"Failed to send: {msg_type.name}")
                return False

        except Exception as e:
            logger.error(f"Send failed: {e}")
            return False

    def send_ack(self, original_message: UARTMessage) -> bool:
        """Send ACK for received message"""
        if not self.serial_connection:
            logger.error("UART not connected")
            return False

        try:
            ack_message = UARTProtocol.create_ack(original_message)
            frame = UARTProtocol.encode_message(ack_message)

            bytes_written = self.serial_connection.write(frame)
            if bytes_written is not None and bytes_written > 0:
                logger.debug(f"Sent ACK for {original_message.msg_type.name} (ID: {original_message.msg_id})")
                return True
            return False

        except Exception as e:
            logger.error(f"Failed to send ACK: {e}")
            return False

    def receive_messages(self) -> List[UARTMessage]:
        """Receive and decode messages"""
        messages = []

        if not self.serial_connection:
            return messages

        try:
            # Check if data is available
            if self.serial_connection.in_waiting > 0:
                data = self.serial_connection.read(self.serial_connection.in_waiting)

                if data:
                    # Simple frame extraction (assumes complete frames)
                    i = 0
                    while i < len(data):
                        if data[i] == UARTProtocol.START_BYTE and i + 4 < len(data):
                            payload_length = data[i + 3]
                            frame_length = 5 + payload_length  # START + TYPE + ID + LENGTH + PAYLOAD + END

                            if i + frame_length <= len(data):
                                frame = data[i:i + frame_length]
                                message = UARTProtocol.decode_frame(frame)
                                if message:
                                    messages.append(message)
                                    logger.debug(f"Received: {message.msg_type.name} (ID: {message.msg_id})")
                                else:
                                    logger.error(f"FAILED TO DECODE FRAME: {frame.hex()}")
                                i += frame_length
                            else:
                                logger.warning(
                                    f"Incomplete frame at position {i}, need {frame_length} bytes but only have {len(data) - i}")
                                break
                        else:
                            i += 1

        except Exception as e:
            logger.error(f"Receive failed: {e}")

        return messages

    def start(self) -> bool:
        """Start UART communication"""
        return self.connect()

    def stop(self) -> None:
        """Stop UART communication"""
        self.disconnect()

    # Convenience methods for common operations
    def control_actuator(self, actuator_type: int, action: int) -> bool:
        """Control actuator - payload format: [actuator type, action]"""
        payload = struct.pack('<BB', actuator_type, action)
        return self.send_message(MessageType.ACTUATOR_MOVEMENT, payload)

    def control_light(self, position: int, light_color: int, light_type: int) -> bool:
        """Control light - payload format: [position, light_color, light_type]"""
        payload = struct.pack('<BBB', position, light_color, light_type)
        return self.send_message(MessageType.LIGHT_MANAGEMENT, payload)

    def control_door(self, action: int) -> bool:
        """Control door blocking mechanism - payload format: [action]"""
        payload = struct.pack('<B', action)
        return self.send_message(MessageType.DOOR_CONTROL, payload)

    def turn_all_lights_off(self) -> bool:
        """Turn off all lights"""
        results = [
            self.control_light(LightPosition.CONTAINER, LightColor.DISABLE_ALL, LightType.STEADY),
            self.control_light(LightPosition.COVER, LightColor.DISABLE_ALL, LightType.STEADY)
        ]
        return all(results)

    def turn_cover_light_off(self) -> bool:
        """Turn off cover light"""
        return self.control_light(LightPosition.COVER, LightColor.DISABLE_ALL, LightType.STEADY)

    def turn_container_light_off(self) -> bool:
        """Turn off container light"""
        return self.control_light(LightPosition.CONTAINER, LightColor.DISABLE_ALL, LightType.STEADY)

    # Convenience actuator methods
    def store_cover(self) -> bool:
        """Store cover (open and close)"""
        return self.control_actuator(ActuatorType.COVER, ActuatorAction.STORE)

    def open_cover(self) -> bool:
        """Open the cover"""
        return self.control_actuator(ActuatorType.COVER, ActuatorAction.OPEN)

    def close_cover(self) -> bool:
        """Close the cover"""
        return self.control_actuator(ActuatorType.COVER, ActuatorAction.CLOSE)

    def store_container(self) -> bool:
        """Store container (open and close)"""
        return self.control_actuator(ActuatorType.CONTAINER, ActuatorAction.STORE)

    def open_container(self) -> bool:
        """Open the container"""
        return self.control_actuator(ActuatorType.CONTAINER, ActuatorAction.OPEN)

    def close_container(self) -> bool:
        """Close the container"""
        return self.control_actuator(ActuatorType.CONTAINER, ActuatorAction.CLOSE)

    # Convenience light methods
    def set_cover_light_white(self) -> bool:
        """Set cover light to white"""
        return self.control_light(LightPosition.COVER, LightColor.WHITE_ON, LightType.STEADY)

    def set_cover_light_green(self) -> bool:
        """Set cover light to green"""
        return self.control_light(LightPosition.COVER, LightColor.GREEN_ON, LightType.STEADY)

    def set_cover_light_red(self) -> bool:
        """Set cover light to red"""
        return self.control_light(LightPosition.COVER, LightColor.RED_ON, LightType.STEADY)

    def set_container_light_white(self) -> bool:
        """Set container light to white"""
        return self.control_light(LightPosition.CONTAINER, LightColor.WHITE_ON, LightType.STEADY)

    def set_container_light_green(self) -> bool:
        """Set container light to green"""
        return self.control_light(LightPosition.CONTAINER, LightColor.GREEN_ON, LightType.STEADY)

    def set_container_light_red(self) -> bool:
        """Set container light to red"""
        return self.control_light(LightPosition.CONTAINER, LightColor.RED_ON, LightType.STEADY)

    def set_error_state(self) -> bool:
        """Set hardware to error state (red container light)"""
        return self.set_container_light_red()

    # Convenience door control methods
    def block_doors(self) -> bool:
        """Block doors"""
        return self.control_door(DoorAction.BLOCK)

    def unblock_doors(self) -> bool:
        """Unblock doors"""
        return self.control_door(DoorAction.UNBLOCK)

    def wait_for_ack(self, timeout: float = 5.0) -> bool:
        """
        Wait for ACK from micro with timeout.

        IMPORTANT: This method does NOT call process_messages() to avoid recursion.
        It only processes incoming messages directly without triggering automatic sequences.
        Automatic sequences are checked in the main process_messages() loop only.

        This prevents the infinite recursion issue where:
        - wait_for_ack() calls process_messages()
        - process_messages() calls _check_automatic_sequences()
        - _check_automatic_sequences() triggers SEQ4
        - SEQ4 calls wait_for_ack() again (creating infinite recursion)
        """
        self._waiting_for_ack = True
        self._last_ack_id = None

        start_time = time.time()
        while self._waiting_for_ack and (time.time() - start_time) < timeout:
            # Direct message processing WITHOUT calling process_messages() to avoid recursion
            messages = self.receive_messages()
            for message in messages:
                # Handle ACK messages
                if message.msg_type == MessageType.ACK:
                    self._handle_ack(message)
                    logger.debug(f"ACK received during wait_for_ack")
                # Handle sensor messages but send ACK back
                elif message.msg_type == MessageType.SENSOR_STATE_CHANGE:
                    self._handle_sensor_change(message)
                    self.send_ack(message)
                # Handle button press
                elif message.msg_type == MessageType.BUTTON_PUSHED:
                    self._handle_button_press(message)
                    self.send_ack(message)
                # Handle error messages
                elif message.msg_type == MessageType.ERROR_MSG:
                    self._handle_error_message(message)
                    self.send_ack(message)
                # Send ACK for any other message types
                else:
                    self.send_ack(message)

            time.sleep(0.1)  # Small delay to prevent busy waiting

        return not self._waiting_for_ack  # True if ACK received, False if timeout

    def wait_for_ack_or_sensor(self, timeout: float = 10.0) -> tuple[bool, str]:
        """
        Wait for either ACK or sensor change message from micro
        Returns: (success, message_type) where message_type is 'ack' or 'sensor'
        """
        self._waiting_for_ack = True
        self._last_ack_id = None
        self._sensor_received = False

        start_time = time.time()
        while self._waiting_for_ack and (time.time() - start_time) < timeout:
            messages = self.receive_messages()
            for message in messages:
                if message.msg_type == MessageType.ACK:
                    self._handle_ack(message)
                    return True, 'ack'
                elif message.msg_type == MessageType.SENSOR_STATE_CHANGE:
                    # Send ACK for sensor message but don't handle the sequence
                    self.send_ack(message)
                    return True, 'sensor'
            time.sleep(0.1)

        return False, 'timeout'

    def get_sensor_status(self) -> bool:
        """Get sensor status - no payload"""
        return self.send_message(MessageType.GET_SENSOR_STATUS)

    def restart_device(self) -> bool:
        """Restart device - no payload"""
        return self.send_message(MessageType.RESTART)

    # NOTE: The following message types are sent BY MICRO TO PI, not Pi to Micro:
    # - BUTTON_PUSHED (0x06): Micro notifies Pi of button press
    # - SENSOR_STATE_CHANGE (0x02): Micro notifies Pi of sensor changes  
    # - ERROR_MSG (0x07): Micro sends error messages to Pi
    # These should be received and handled in the main loop, not sent by Pi

    def process_messages(self) -> None:
        """Process all incoming UART messages and handle sequences"""
        messages = self.receive_messages()
        for message in messages:
            self._process_message(message)

        # Check for automatic sequence triggers
        self._check_automatic_sequences()

    def _process_message(self, message: UARTMessage) -> None:
        """Process a single UART message"""
        try:
            # Send ACK for all received messages except ACK itself
            if message.msg_type != MessageType.ACK:
                success = self.send_ack(message)
                if not success:
                    logger.error(f"Failed to send ACK for {message.msg_type.name}")

            # Handle message based on type
            handler = self.message_handlers.get(message.msg_type)
            if handler:
                handler(message)
            else:
                logger.warning(f"No handler for message type {message.msg_type.name}")

        except Exception as e:
            logger.error(f"Error processing message {message.msg_type.name}: {e}")

    def _handle_button_press(self, message: UARTMessage) -> None:
        """Handle button press - trigger SEQ1"""
        logger.info("Button press received")

        # Check if device is inactive
        if self._is_device_inactive():
            logger.warning("Button press ignored - device is inactive")
            return

        logger.info("Triggering SEQ1")
        self._execute_sequence_1()

    def _handle_sensor_change(self, message: UARTMessage) -> None:
        """Handle sensor state change - trigger SEQ2 or SEQ3"""
        if len(message.payload) >= 2:
            sensor_type = message.payload[0]
            new_status = message.payload[1]

            logger.info(f"Sensor change: type={sensor_type}, status={new_status}")

            # Check if device is inactive
            if self._is_device_inactive():
                logger.warning("Sensor change ignored - device is inactive")
                return

            # Update sensor state tracking  
            if sensor_type in self.sensor_states:
                self.sensor_states[sensor_type] = (new_status == SensorStatus.DETECTION)

            # Handle sequences based on sensor changes
            if sensor_type == SensorType.COVER and new_status == SensorStatus.DETECTION:
                logger.info("Cover detected - triggering SEQ2")
                self._execute_sequence_2()
            elif sensor_type == SensorType.CONTAINER and new_status == SensorStatus.DETECTION:
                logger.info("Container detected - triggering SEQ3")
                self._execute_sequence_3()
        else:
            logger.warning("Invalid sensor state change payload")

    def _handle_error_message(self, message: UARTMessage) -> None:
        """Handle error message from micro"""
        error_text = message.payload.decode('utf-8', errors='ignore')
        logger.error(f"Hardware error from micro: {error_text}")
        self.set_error_state()

    def _handle_ack(self, message: UARTMessage) -> None:
        """Handle ACK from micro"""
        logger.debug(f"Received ACK from micro for message ID {message.msg_id}")
        # Store received ACK for waiting mechanism
        self._last_ack_id = message.msg_id
        self._waiting_for_ack = False

    def _execute_sequence_1(self) -> bool:
        """
        SEQ1: Button Press Activation
        Steps:
        i) User pushes button and Micro send the message (already handled)
        ii) We send ACK (already handled)
        iii) We send message to unblock door solenoids
        iv) We WAIT for ACK from micro before moving on
        v) We wait 1 second
        vi) We send message to block door solenoids
        vii) We WAIT for ACK from micro before moving on  
        viii) We send message to turn WHITE light on for COVER
        ix) We WAIT for ACK from micro before moving on
        x) We send message to turn WHITE light on for CONTAINER
        xi) We WAIT for ACK from micro before moving on
        """
        try:
            logger.info("Starting SEQ1: Button Press Activation")

            # Step iii: Send message to unblock door solenoids
            logger.info("SEQ1 Step iii: Unblocking door solenoids")
            if not self.unblock_doors():
                logger.error("Failed to send unblock doors command")
                return False

            # Step iv: Wait for ACK from micro
            logger.info("SEQ1 Step iv: Waiting for ACK from micro for unblock doors")
            if not self.wait_for_ack(timeout=5.0):
                logger.error("Timeout waiting for ACK for unblock doors command")
                return False

            # Step v: Wait 1 second
            logger.info("SEQ1 Step v: Waiting 1 second")
            time.sleep(1)

            # Step vi: Send message to block door solenoids
            logger.info("SEQ1 Step vi: Blocking door solenoids")
            if not self.block_doors():
                logger.error("Failed to send block doors command")
                return False

            # Step vii: Wait for ACK from micro
            logger.info("SEQ1 Step vii: Waiting for ACK from micro for block doors")
            if not self.wait_for_ack(timeout=5.0):
                logger.error("Timeout waiting for ACK for block doors command")
                return False

            # Step viii: Send message to turn WHITE light on for COVER
            logger.info("SEQ1 Step viii: Turning on WHITE light for COVER")
            if not self.set_cover_light_white():
                logger.error("Failed to send COVER white light command")
                return False

            # Step ix: Wait for ACK from micro
            logger.info("SEQ1 Step ix: Waiting for ACK from micro for COVER light")
            if not self.wait_for_ack(timeout=5.0):
                logger.error("Timeout waiting for ACK for COVER light command")
                return False

            # Step x: Send message to turn WHITE light on for CONTAINER
            logger.info("SEQ1 Step x: Turning on WHITE light for CONTAINER")
            if not self.set_container_light_white():
                logger.error("Failed to send CONTAINER white light command")
                return False

            # Step xi: Wait for ACK from micro
            logger.info("SEQ1 Step xi: Waiting for ACK from micro for CONTAINER light")
            if not self.wait_for_ack(timeout=5.0):
                logger.error("Timeout waiting for ACK for CONTAINER light command")
                return False

            # Track light activation for timeout handling
            self._seq1_lights_active = True
            self._seq1_activation_time = time.time()

            logger.info("SEQ1 completed successfully - system now waiting for cover/container detection")
            return True

        except Exception as e:
            logger.error(f"SEQ1 failed: {e}")
            self.set_error_state()
            return False

    def _execute_sequence_2(self) -> bool:
        """
        SEQ2: Cover Detection and Storage
        Steps:
        i) User enters cover and Micro send the message for cover detection (already handled)
        ii) We send ACK (already handled)
        iii) We send message to turn Green light on for COVER
        iv) We WAIT for ACK from micro before moving on
        v) We mark SEQ2 as completed with timestamp
        """
        try:
            logger.info("Starting SEQ2: Cover Detection and Storage")

            # Turn off SEQ1 lights if active
            if self._seq1_lights_active:
                self._seq1_lights_active = False
                self._seq1_activation_time = None

            # Step iii: Send message to turn Green light on for COVER
            logger.info("SEQ2 Step iii: Turning on GREEN light for COVER")
            if not self.set_cover_light_green():
                logger.error("Failed to send COVER green light command")
                return False

            # Step iv: Wait for ACK from micro
            logger.info("SEQ2 Step iv: Waiting for ACK from micro for COVER green light")
            if not self.wait_for_ack(timeout=5.0):
                logger.error("Timeout waiting for ACK for COVER green light command")
                return False

            # Step v: Mark SEQ2 as completed with timestamp
            logger.info("SEQ2 Step v: Marking sequence as completed")
            self._seq2_completed = True
            self._seq2_completion_time = time.time()

            logger.info("SEQ2 completed successfully")
            return True

        except Exception as e:
            logger.error(f"SEQ2 failed: {e}")
            self.set_error_state()
            return False

    def _execute_sequence_3(self) -> bool:
        """
        SEQ3: Container Detection and QR Validation (Revised)
        Steps:
        i) User enters container, micro sends message (already handled)
        ii) We send ACK (already handled)
        iii) Pi waits for QR code scan
        iv) Pi validates QR against database
        v) If valid: send green light for container (feedback)
        vi) If invalid: send red light for container (feedback)
        vii) We WAIT for ACK from micro
        viii) We mark SEQ3 as completed with timestamp
        """
        try:
            logger.info("Starting SEQ3: Container Detection and QR Validation")

            # Turn off SEQ1 lights if active
            if self._seq1_lights_active:
                self._seq1_lights_active = False
                self._seq1_activation_time = None

            # Step iii: Start waiting for QR scan
            logger.info("SEQ3 Step iii: Waiting for container QR scan...")
            self._waiting_for_qr = True
            self._qr_timeout_start = time.time()
            self._container_qr_code = None

            # Wait for QR scan with timeout (30 seconds)
            # The QR code will be provided by the USB scanner via main.py _handle_qr_scan callback
            # READING QR FOR 30 SECONDS TILL WE READ A VALID QR
            qr_timeout = 30.0
            while self._waiting_for_qr and (time.time() - self._qr_timeout_start) < qr_timeout:
                # Simple wait - no UART messages to process during QR wait
                time.sleep(0.1)

            if not self._container_qr_code:
                logger.error("QR scan timeout - no QR code received")
                return self._handle_seq3_invalid_qr("QR scan timeout")

            # Step iv: Validate QR against database
            logger.info(f"SEQ3 Step iv: Validating QR code: {self._container_qr_code}")
            validation_result = self._validate_container_qr(self._container_qr_code)

            if validation_result:
                return self._handle_seq3_valid_qr()
            else:
                return self._handle_seq3_invalid_qr("QR validation failed")

        except Exception as e:
            logger.error(f"SEQ3 failed: {e}")
            self.set_error_state()
            return False

    def _validate_container_qr(self, qr_code: str) -> bool:
        """Validate QR code with URL format, hash verification, server request and offline fallback"""
        try:
            # Step 1: Process QR code with new URL validation and hash verification
            if not self.qr_processor:
                logger.error("QR processor not available")
                return False
            
            qr_result = self.qr_processor.process_qr_code(qr_code)
            
            # Step 2: Check for fraud attempts
            if qr_result.is_fraud_attempt or qr_result.validation.value == "fraud_attempt":
                logger.warning(f"Fraud attempt detected: {qr_result.error_message}")
                # Log fraud attempt to audit system
                if self.audit_logger:
                    self.audit_logger.log_security_event(
                        event_type="fraud_attempt",
                        description=f"QR fraud attempt detected: {qr_result.error_message}",
                        details={
                            "qr_code": qr_code,
                            "validation_result": qr_result.validation.value,
                            "error": qr_result.error_message
                        }
                    )
                return False
            
            # Step 3: Check if QR validation passed
            if qr_result.validation.value != "valid" or not qr_result.container_id:
                logger.warning(f"QR validation failed: {qr_result.error_message}")
                return False
            
            # Step 4: Use the extracted container code for server validation
            container_code = qr_result.container_id
            logger.info(f"QR URL validated successfully, extracted code: {container_code}")

            # Step 5: Try server validation first
            server_response = self._validate_with_server(container_code)

            if server_response is not None:
                # Server responded - use server decision
                return self._handle_server_response(container_code, server_response)
            else:
                # Server failed/timeout - use offline fallback
                return self._handle_offline_fallback(container_code)

        except Exception as e:
            logger.error(f"QR validation error: {e}")
            return False

    def _validate_with_server(self, qr_code: str) -> Optional[Dict[str, Any]]:
        """Make HTTP request to server for QR validation"""
        try:
            if not self.api_service or not self.db_manager:
                logger.warning("No API service or database manager available for server validation")
                return None

            # First, get container from local database using QR code
            container = self.db_manager.containers.get_by_qr_code(qr_code)
            if not container:
                logger.warning(f"Container not found in local database for QR: {qr_code}")
                return None

            logger.info(f"Validating container {container.id} with server (QR: {qr_code})")
            response = self.api_service.validate_container(container.id)

            if response:
                logger.info(f"Server response received for container {container.id}")
                return response
            else:
                logger.warning(f"Server validation failed for container {container.id}")
                return None

        except Exception as e:
            logger.error(f"Server validation request failed: {e}")
            return None

    def _handle_server_response(self, qr_code: str, response: Dict[str, Any]) -> bool:
        """Handle server response and update local database"""
        try:
            # Extract data from response structure
            container_data = response.get('containerData', {})
            is_returnable = container_data.get('isReturnable', False)

            logger.debug(f"Raw server response: {response}")
            logger.debug(f"Extracted isReturnable: {is_returnable}, containerData: {container_data}")

            logger.info(f"Server response - isReturnable: {is_returnable}")
            container = self.db_manager.containers.get_by_qr_code(qr_code)
            # Update local database with server response
            if container_data:
                container_data['id'] = container.id
                self._update_local_container(qr_code, container_data)

            # Server validation logic based on isReturnable field
            if not is_returnable:
                # Server says reject - respect server decision
                reason = "Container return not valid"
                logger.info(f"Container rejected by server: {reason}")

                if self.audit_logger:
                    self.audit_logger.log_return_invalid(
                        container.id,
                        f"Server rejection - QR: {qr_code}, Reason: {reason}"
                    )
                return False
            else:
                # Server says accept
                logger.info(f"Container accepted by server: {qr_code}")

                if self.audit_logger:
                    self.audit_logger.log_return_valid(
                        container.id,
                        f"Server acceptance - QR: {qr_code}"
                    )
                return True

        except Exception as e:
            logger.error(f"Error handling server response: {e}")
            return False

    def _handle_offline_fallback(self, qr_code: str) -> bool:
        """Handle offline fallback validation using local database"""
        try:
            logger.info(f"Using offline fallback validation for QR: {qr_code}")

            if not self.db_manager:
                logger.error("No database manager available for offline validation")
                return False

            # Get container from local database
            container = self.db_manager.containers.get_by_qr_code(qr_code)

            if not container:
                logger.warning(f"Container not found in local database: {qr_code}")
                return False

            # Check if returnable
            if not container.is_returnable:
                logger.warning(f"Container not returnable in local database: {qr_code}")
                if self.audit_logger:
                    self.audit_logger.log_return_invalid(
                        container.id,
                        f"Offline validation failed - not returnable - QR: {qr_code}",
                        is_offline=True
                    )
                return False

            # Check due date if present
            if container.due_date:
                current_time = datetime.now(timezone.utc)
                if container.due_date < current_time:
                    logger.warning(f"Container expired - due: {container.due_date}, current: {current_time}")
                    if self.audit_logger:
                        self.audit_logger.log_return_invalid(
                            container.id,
                            f"Offline validation failed - expired - QR: {qr_code}, Due: {container.due_date.isoformat()}",
                            is_offline=True
                        )
                    return False

            # Container is returnable and not expired
            logger.info(f"Container accepted via offline validation: {qr_code}")
            if self.audit_logger:
                self.audit_logger.log_return_valid(
                    container.id,
                    f"Offline validation success - QR: {qr_code}",
                    is_offline=True
                )
            return True

        except Exception as e:
            logger.error(f"Error in offline fallback validation: {e}")
            return False

    def _update_local_container(self, qr_code: str, container_data: Dict[str, Any]) -> None:
        """Update local database with server response data"""
        try:
            if not self.db_manager:
                logger.warning("No database manager available for updating container")
                return

            container_id = container_data.get('id')
            is_returnable = container_data.get('isReturnable')
            updated_at_str = container_data.get('updatedAt')

            logger.debug(
                f"Server response data - id: {container_id}, isReturnable: {is_returnable}, updatedAt: {updated_at_str}")

            if not container_id:
                logger.warning("No container ID in server response")
                return

            # Parse updated timestamp
            updated_at = None
            if updated_at_str:
                try:
                    updated_at = datetime.fromisoformat(
                        updated_at_str.replace('Z', '+00:00')
                    )
                except ValueError as e:
                    logger.warning(f"Invalid updatedAt timestamp: {updated_at_str} - {e}")

            # Check if container exists
            existing_container = self.db_manager.containers.get_by_qr_code(qr_code)

            if existing_container:
                # Update existing container
                updates = {}
                if is_returnable is not None:
                    updates['is_returnable'] = bool(is_returnable)
                    logger.debug(f"Setting is_returnable update: {bool(is_returnable)}")
                if updated_at:
                    updates['updatedAt'] = updated_at.isoformat()

                if updates:
                    self.db_manager.containers.update(existing_container.id, updates)
                    logger.info(f"Updated existing container {container_id} with server data")
            else:
                # Create new container
                from ..database.models import ContainerCreate
                container_create = ContainerCreate(
                    qr_code=qr_code,
                    is_returnable=is_returnable if is_returnable is not None else True,
                    due_date=updated_at  # Using updatedAt as due_date if no specific due_date
                )
                self.db_manager.containers.create(container_create)
                logger.info(f"Created new container {container_id} from server data")

        except Exception as e:
            logger.error(f"Error updating local container: {e}")

    def _handle_seq3_valid_qr(self) -> bool:
        """Handle valid QR code flow for SEQ3"""
        try:
            logger.info("SEQ3 Step v: QR validation successful - sending green container light")

            # Step v: Send green light for container (feedback)
            logger.info("SEQ3 Step v: Setting container light to green (validation feedback)")
            if not self.set_container_light_green():
                logger.error("Failed to set container light to green")
                return False

            # Step vii: Wait for ACK
            logger.info("SEQ3 Step vii: Waiting for ACK from micro for green light")
            if not self.wait_for_ack(timeout=5.0):
                logger.error("Timeout waiting for ACK for green light")
                return False

            # Step viii: Mark SEQ3 as completed with timestamp
            logger.info("SEQ3 Step viii: Marking sequence as completed")
            self._seq3_completed = True
            self._seq3_completion_time = time.time()

            logger.info("SEQ3 completed successfully")
            return True

        except Exception as e:
            logger.error(f"SEQ3 valid QR handling failed: {e}")
            return False

    def _handle_seq3_invalid_qr(self, reason: str) -> bool:
        """Handle invalid QR code flow for SEQ3"""
        try:
            logger.warning(f"QR validation failed: {reason}")

            # Step vi: Send red light for container (feedback)
            logger.info("SEQ3 Step vi: Setting container light to red (validation feedback)")
            if not self.set_container_light_red():
                logger.error("Failed to set container light to red")
                return False

            # Step vii: Wait for ACK
            logger.info("SEQ3 Step vii: Waiting for ACK from micro for red light")
            if not self.wait_for_ack(timeout=5.0):
                logger.error("Timeout waiting for ACK for red light")
                return False

            # Step viii: Mark SEQ3 as completed with timestamp (even if invalid)
            logger.info("SEQ3 Step viii: Marking sequence as completed")
            self._seq3_completed = True
            self._seq3_completion_time = time.time()

            logger.info("SEQ3 completed successfully")
            return True

        except Exception as e:
            logger.error(f"SEQ3 invalid QR handling failed: {e}")
            return False

    def _wait_for_container_removal(self) -> bool:
        """Wait for container removal and complete sequence"""
        try:
            logger.info("Waiting for container removal...")

            # Wait for container not detected message from micro
            container_removed = False
            timeout = 60.0  # 1 minute timeout
            start_time = time.time()

            while not container_removed and (time.time() - start_time) < timeout:
                messages = self.receive_messages()
                for message in messages:
                    if (message.msg_type == MessageType.SENSOR_STATE_CHANGE and
                            len(message.payload) >= 2 and
                            message.payload[0] == SensorType.CONTAINER and
                            message.payload[1] == SensorStatus.NO_DETECTION):  # Container not detected

                        # Send ACK
                        self.send_ack(message)
                        container_removed = True
                        logger.info("Container removal detected")
                        break
                    elif message.msg_type != MessageType.ACK:
                        # Send ACK for any other messages
                        self.send_ack(message)

                time.sleep(0.1)

            if not container_removed:
                logger.error("Timeout waiting for container removal")
                return False

            # Turn off all lights
            logger.info("Turning off all lights")
            if not self.turn_all_lights_off():
                logger.error("Failed to turn off all lights")
                return False

            # Wait for ACK
            if not self.wait_for_ack(timeout=5.0):
                logger.error("Timeout waiting for ACK for lights off")
                return False

            logger.info("SEQ3 completed successfully")
            return True

        except Exception as e:
            logger.error(f"Container removal handling failed: {e}")
            return False

    def _execute_sequence_4(self) -> bool:
        """
        SEQ4: Combined Storage Operations (Revised)
        Steps:
        i) Check trigger conditions (SEQ2/3 completed + 3+ minutes elapsed)
        ii) Send container store command
        iii) We WAIT for ACK from micro
        iv) Send cover store command
        v) We WAIT for ACK from micro
        vi) Wait for cover removal detection from sensors
        vii) Wait for container removal detection from sensors
        viii) Turn off all lights
        ix) We WAIT for ACK from micro
        x) Reset sequence completion flags
        """
        # Set guard flag to prevent re-entry during execution
        self._seq4_in_progress = True

        try:
            logger.info("Starting SEQ4: Combined Cover and Container Storage")

            # Step ii: Send container store command
            logger.info("SEQ4 Step ii: Sending container store command")
            if not self.store_container():
                logger.error("Failed to send container store command")
                return False

            # Step iii: Wait for ACK from micro
            logger.info("SEQ4 Step iii: Waiting for ACK from micro for container store")
            if not self.wait_for_ack(timeout=5.0):
                logger.error("Timeout waiting for ACK for container store command")
                return False

            # Step iv: Send cover store command
            logger.info("SEQ4 Step iv: Sending cover store command")
            if not self.store_cover():
                logger.error("Failed to send cover store command")
                return False

            # Step v: Wait for ACK from micro
            logger.info("SEQ4 Step v: Waiting for ACK from micro for cover store")
            if not self.wait_for_ack(timeout=5.0):
                logger.error("Timeout waiting for ACK for cover store command")
                return False

            # Step vi-vii: Wait for removal detection from sensors
            logger.info("SEQ4 Step vi-vii: Waiting for cover and container removal detection")
            if not self._wait_for_both_removals():
                logger.error("Failed waiting for item removals")
                return False

            # Step viii: Turn off all lights
            logger.info("SEQ4 Step viii: Turning off all lights")
            if not self.turn_all_lights_off():
                logger.error("Failed to turn off all lights")
                return False

            # Step ix: Wait for ACK from micro
            logger.info("SEQ4 Step ix: Waiting for ACK from micro for lights off")
            if not self.wait_for_ack(timeout=5.0):
                logger.error("Timeout waiting for ACK for lights off")
                return False

            # Step x: Reset sequence completion flags
            logger.info("SEQ4 Step x: Resetting sequence completion flags")
            self._seq2_completed = False
            self._seq2_completion_time = None
            self._seq3_completed = False
            self._seq3_completion_time = None

            logger.info("SEQ4 completed successfully")
            return True

        except Exception as e:
            logger.error(f"SEQ4 failed: {e}")
            self.set_error_state()
            return False

        finally:
            # Always reset the guard flag when SEQ4 execution ends (success or failure)
            self._seq4_in_progress = False

    def _execute_sequence_5(self) -> bool:
        """
        SEQ5: Error Recovery (Simplified)
        Steps:
        i) Check for persistent sensor detection after SEQ4
        ii) Re-open actuators to free stuck items  
        iii) We WAIT for ACK from micro
        iv) If items remain stuck after retry:
           - Activate red light for positions where sensor still detects
           - Log error condition for maintenance attention
        v) We WAIT for ACK from micro
        """
        try:
            logger.info("Starting SEQ5: Error Recovery")

            # Step ii: Re-open actuators to free stuck items
            logger.info("SEQ5 Step ii: Re-opening container actuator")
            if not self.open_container():
                logger.error("Failed to open container actuator")
                return False

            if not self.wait_for_ack(timeout=5.0):
                logger.error("Timeout waiting for ACK for container open")
                return False

            logger.info("SEQ5 Step ii: Re-opening cover actuator")
            if not self.open_cover():
                logger.error("Failed to open cover actuator")
                return False

            # Step iii: Wait for ACK from micro
            logger.info("SEQ5 Step iii: Waiting for ACK from micro for cover open")
            if not self.wait_for_ack(timeout=5.0):
                logger.error("Timeout waiting for ACK for cover open")
                return False

            # Give time for items to fall out
            time.sleep(2)

            # Step iv: Check for persistent detection and handle stuck items
            logger.info("SEQ5 Step iv: Checking for persistent detection after retry")
            warning_sent = False

            if self.sensor_states.get(SensorType.COVER, False):
                logger.error("Cover still detected after retry - activating red warning light")
                if not self.set_cover_light_red():
                    logger.error("Failed to set cover red warning light")
                else:
                    warning_sent = True
                    # Log error condition for maintenance
                    logger.error("MAINTENANCE REQUIRED: Cover actuator appears to be jammed")

            if self.sensor_states.get(SensorType.CONTAINER, False):
                logger.error("Container still detected after retry - activating red warning light")
                if not self.set_container_light_red():
                    logger.error("Failed to set container red warning light")
                else:
                    warning_sent = True
                    # Log error condition for maintenance
                    logger.error("MAINTENANCE REQUIRED: Container actuator appears to be jammed")

            # Step v: Wait for ACK from micro if warning lights were sent
            if warning_sent:
                logger.info("SEQ5 Step v: Waiting for ACK from micro for warning lights")
                if not self.wait_for_ack(timeout=5.0):
                    logger.error("Timeout waiting for ACK for warning lights")
                    return False

            logger.info("SEQ5 completed successfully")
            return True

        except Exception as e:
            logger.error(f"SEQ5 failed: {e}")
            self.set_error_state()
            return False

    def _wait_for_both_removals(self) -> bool:
        """Wait for both cover and container removal detection with explicit ACK handling"""
        try:
            logger.info("Waiting for both cover and container removal...")

            cover_removed = False
            container_removed = False
            timeout = 120.0  # 2 minute timeout
            start_time = time.time()

            while (not cover_removed or not container_removed) and (time.time() - start_time) < timeout:
                messages = self.receive_messages()
                for message in messages:
                    if (message.msg_type == MessageType.SENSOR_STATE_CHANGE and
                            len(message.payload) >= 2):

                        sensor_type = message.payload[0]
                        new_status = message.payload[1]

                        if (sensor_type == SensorType.COVER and
                                new_status == SensorStatus.NO_DETECTION):
                            cover_removed = True
                            logger.info("Cover removal detected - Pi acknowledges")
                            # Update sensor state tracking
                            self.sensor_states[SensorType.COVER] = False

                        elif (sensor_type == SensorType.CONTAINER and
                              new_status == SensorStatus.NO_DETECTION):
                            container_removed = True
                            logger.info("Container removal detected - Pi acknowledges")
                            # Update sensor state tracking  
                            self.sensor_states[SensorType.CONTAINER] = False

                        # Send ACK for sensor messages (as specified)
                        self.send_ack(message)

                    elif message.msg_type != MessageType.ACK:
                        # Send ACK for any other messages
                        self.send_ack(message)

                time.sleep(0.1)

            if not cover_removed or not container_removed:
                logger.error("Timeout waiting for complete removal - some items may be stuck")
                return False

            logger.info("Both items removed successfully")
            return True

        except Exception as e:
            logger.error(f"Error waiting for removals: {e}")
            return False

    def check_sequence_4_trigger(self) -> bool:
        """Check if SEQ4 should be triggered based on timing conditions"""
        # Prevent re-entry if SEQ4 is already in progress
        if self._seq4_in_progress:
            return False

        current_time = time.time()

        # Check trigger conditions
        seq2_ready = (self._seq2_completed and self._seq2_completion_time and
                      (current_time - self._seq2_completion_time) > 180)  # 3 minutes

        seq3_ready = (self._seq3_completed and self._seq3_completion_time and
                      (current_time - self._seq3_completion_time) > 180)  # 3 minutes

        # Combined trigger: either sequence ready after 3+ minutes
        if seq2_ready or seq3_ready:
            logger.info(f"SEQ4 trigger conditions met - SEQ2: {seq2_ready}, SEQ3: {seq3_ready}")
            return True

        return False

    def _check_automatic_sequences(self) -> None:
        """Check and trigger automatic sequences (SEQ1 timeout, SEQ4, SEQ5)"""
        try:
            current_time = time.time()

            # Check for SEQ1 light timeout (1+ minute)
            if (self._seq1_lights_active and self._seq1_activation_time and
                    (current_time - self._seq1_activation_time) > 60):
                logger.info("SEQ1 timeout - turning off all lights")
                self.turn_all_lights_off()
                self._seq1_lights_active = False
                self._seq1_activation_time = None

            # Check for SEQ4 trigger conditions
            if self.check_sequence_4_trigger():
                logger.info("Triggering SEQ4: Combined Storage")
                success = self._execute_sequence_4()

                # Check for SEQ5 after SEQ4 completion
                if success:
                    # Brief delay to check for persistent sensor detection
                    time.sleep(1)
                    if (self.sensor_states.get(SensorType.COVER, False) or
                            self.sensor_states.get(SensorType.CONTAINER, False)):
                        logger.info("Triggering SEQ5: Error Recovery")
                        self._execute_sequence_5()
        except Exception as e:
            logger.error(f"Error in automatic sequence checking: {e}")

    def handle_qr_scan(self, qr_code: str) -> None:
        """Handle QR code scan from main application"""
        if self._waiting_for_qr:
            logger.info(f"QR code received: {qr_code}")
            self._container_qr_code = qr_code
            self._waiting_for_qr = False
        else:
            logger.warning(f"QR code received but not waiting for QR: {qr_code}")

    def reset_to_idle(self) -> None:
        """Reset system to idle state"""
        logger.info("Resetting to idle state")

        try:
            self.turn_all_lights_off()
            self.close_cover()
            self.close_container()
        except Exception as e:
            logger.error(f"Error during reset: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Get UART status"""
        return {
            "connected": self.serial_connection is not None,
            "port": self.port,
            "baudrate": self.baudrate
        }
