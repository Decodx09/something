"""
USB QR scanner for Raspberry Pi container return system.

Reads QR codes from USB-connected QR scanner devices using evdev for HID device access.
Uses file-based communication to isolate QR data from other terminal sessions.
"""

import time
import logging
import os
import threading
from pathlib import Path
from typing import Callable, Optional, Dict, Any
from dataclasses import dataclass

try:
    from evdev import InputDevice, categorize, ecodes
    from .scancode_mapping import get_character, is_modifier_key
    HAS_EVDEV = True
except ImportError:
    HAS_EVDEV = False
    logging.error("evdev not available - QR scanner requires evdev. Install with: sudo apt install python3-evdev")

logger = logging.getLogger(__name__)


@dataclass
class QRScanEvent:
    """Represents a QR scan event."""
    timestamp: float
    qr_code: str
    source: str = "usb"


class QRScanner:
    """
    USB QR scanner using evdev for HID device access with file-based communication.
    
    Reads QR codes from USB QR scanner devices using evdev to access HID devices directly.
    Uses temporary file to isolate QR data from other terminal sessions.
    """
    
    def __init__(self, uart_manager=None, audit_logger=None, device_path="/dev/hidraw2"):
        """Initialize the QR scanner."""
        if not HAS_EVDEV:
            raise RuntimeError("evdev is required for QR scanner. Install with: sudo apt install python3-evdev")
        
        self._running = False
        self._scan_callbacks: list = []
        self._current_scan = ""
        self._last_char_time = time.time()
        self._scanner_thread = None
        self._shift_pressed = False
        
        # Integration components
        self.uart_manager = uart_manager
        self.audit_logger = audit_logger
        
        # Configuration
        self.min_qr_length = 6
        self.max_qr_length = 200  # Match QR processor max length (for URL format)
        self.scan_timeout = 2.0  # Max time between characters
        self.scan_enabled = True  # Can be toggled to ignore keyboard input
        self.device_path = device_path
        self.qr_file_path = Path("qr_scan_data.txt")
        
        # Verify device access
        self._verify_device_access()
        
        logger.info(f"QR scanner initialized with evdev on {self.device_path}")
    
    def _verify_device_access(self):
        """Verify that the HID device can be accessed."""
        if not os.path.exists(self.device_path):
            raise RuntimeError(f"QR scanner device not found: {self.device_path}")
        
        try:
            device = InputDevice(self.device_path)
            device.close()
        except (OSError, PermissionError) as e:
            raise RuntimeError(f"Cannot access QR scanner device {self.device_path}: {e}. "
                             f"Try: sudo usermod -a -G input $USER")
    
    def add_scan_callback(self, callback: Callable[[QRScanEvent], None]):
        """Add callback for QR scan events."""
        self._scan_callbacks.append(callback)
    
    def start_scanning(self):
        """Start QR code scanning."""
        if self._running:
            logger.warning("QR scanner already running")
            return
        
        self._running = True
        
        try:
            self._scanner_thread = threading.Thread(
                target=self._evdev_scan_loop,
                daemon=True,
                name="QRScannerEvdev"
            )
            self._scanner_thread.start()
            logger.info(f"QR scanner started with evdev on {self.device_path}")
        except Exception as e:
            logger.error(f"Failed to start evdev scanning: {e}")
            self._running = False
    
    def _evdev_scan_loop(self):
        """Main loop for evdev-based scanning."""
        device = None
        try:
            device = InputDevice(self.device_path)
            logger.info(f"Listening for QR scans on {device.name} ({self.device_path})")
            
            for event in device.read_loop():
                if not self._running:
                    break
                
                if not self.scan_enabled:
                    continue
                
                if event.type == ecodes.EV_KEY and event.value == 1:  # Key down
                    self._process_evdev_keypress(event.code)
                    
        except Exception as e:
            logger.error(f"Error in evdev scan loop: {e}")
        finally:
            if device:
                device.close()
    
    def _process_evdev_keypress(self, scancode: int):
        """Process a keypress from evdev."""
        try:
            current_time = time.time()
            
            # Handle modifier keys
            if is_modifier_key(scancode):
                if scancode in [42, 54]:  # Left/Right Shift
                    self._shift_pressed = True
                return
            
            # Get character for this scancode
            char = get_character(scancode, self._shift_pressed)
            
            # Reset shift state after processing
            self._shift_pressed = False
            
            if not char:
                return
            
            # Handle Enter key - end of scan
            if char == "\n":
                if self._current_scan:
                    self._write_qr_to_file(self._current_scan.strip())
                    self._current_scan = ""
                return
            
            # Reset scan if too much time passed
            if current_time - self._last_char_time > self.scan_timeout:
                self._current_scan = ""
            
            self._current_scan += char
            self._last_char_time = current_time
            
            # Safety check for overly long scans
            if len(self._current_scan) > self.max_qr_length:
                logger.warning(f"QR scan too long, resetting: {self._current_scan[:20]}...")
                self._current_scan = ""
                
        except Exception as e:
            logger.error(f"Error processing evdev keypress: {e}")
    
    def _write_qr_to_file(self, qr_code: str):
        """Write QR code to temporary file atomically."""
        try:
            # Use atomic write to prevent race conditions
            temp_path = self.qr_file_path.with_suffix('.tmp')
            with open(temp_path, 'w') as f:
                f.write(qr_code)
            temp_path.replace(self.qr_file_path)
            logger.debug(f"QR code written to file: {qr_code}")
        except Exception as e:
            logger.error(f"Failed to write QR to file: {e}")
    
    def _read_qr_from_file(self) -> Optional[str]:
        """Read QR code from temporary file and clear it atomically."""
        try:
            if not self.qr_file_path.exists():
                return None
            
            # Read and delete atomically to prevent race conditions
            try:
                with open(self.qr_file_path, 'r') as f:
                    qr_code = f.read().strip()
                
                # Clear the file after reading
                self.qr_file_path.unlink()
                
                return qr_code if qr_code else None
                
            except FileNotFoundError:
                # File was already processed by another thread
                return None
            
        except Exception as e:
            logger.error(f"Failed to read QR from file: {e}")
            return None
    
    def stop_scanning(self):
        """Stop QR code scanning."""
        if not self._running:
            return
        
        self._running = False
        
        if self._scanner_thread:
            self._scanner_thread = None
        
        # Clean up temporary file
        try:
            if self.qr_file_path.exists():
                self.qr_file_path.unlink()
        except Exception as e:
            logger.warning(f"Failed to clean up QR file: {e}")
        
        logger.info("QR scanner stopped")
    
    def enable_scanning(self):
        """Enable QR scan processing (default)."""
        self.scan_enabled = True
        logger.debug("QR scanning enabled")
    
    def disable_scanning(self):
        """Disable QR scan processing (ignore keyboard input)."""
        self.scan_enabled = False
        self._current_scan = ""  # Clear any partial scan
        logger.debug("QR scanning disabled")
    
    
    def _process_scan(self, qr_code: str):
        """Process a scanned QR code."""
        try:
            # Clean the QR code using proper decoding approach
            qr_code_raw = qr_code
            
            # If it's bytes, decode with error handling
            if isinstance(qr_code, bytes):
                decoded = qr_code.decode("utf-8", errors="ignore")
            else:
                decoded = qr_code
            
            # Remove null bytes and control characters, keep printable chars
            cleaned = "".join(ch for ch in decoded if ord(ch) >= 32 or ch in '\t\n').strip()
            
            # Look for "https" and remove everything before it
            # This handles any scanner prefix (]Q2\, \000026, etc.)
            https_pos = cleaned.find('https')
            if https_pos > 0:
                cleaned = cleaned[https_pos:]  # Keep everything from "https" onwards
            elif not cleaned.startswith('https'):
                # If no "https" found, it's not a valid URL QR code
                logger.warning(f"No 'https' found in QR code: {cleaned}")
                return
            
            logger.debug(f"QR code raw: {repr(qr_code_raw)} -> cleaned: {repr(cleaned)}")
            
            if not self._validate_qr_format(cleaned):
                logger.warning(f"Invalid QR code format: {cleaned}")
                return
            
            qr_code = cleaned
            scan_event = QRScanEvent(
                timestamp=time.time(),
                qr_code=qr_code,
                source="usb"
            )
            
            logger.info(f"QR code scanned: {scan_event.qr_code}")
            
            # Handle sequence 3 QR directly
            if self.uart_manager and self.uart_manager._waiting_for_qr:
                self.uart_manager._container_qr_code = scan_event.qr_code
                self.uart_manager._waiting_for_qr = False
                logger.info("QR code provided to sequence 3")
                
                # QR scan will be logged by the UART validation process if successful
                return
            
            # Trigger callbacks for other uses
            for callback in self._scan_callbacks:
                try:
                    callback(scan_event)
                except Exception as e:
                    logger.error(f"Error in QR scan callback: {e}")
                    
        except Exception as e:
            logger.error(f"Error processing QR scan: {e}")
            if self.uart_manager:
                self.uart_manager.set_error_state()
    
    def _validate_qr_format(self, qr_code: str) -> bool:
        """Validate QR code format."""
        if not qr_code or not isinstance(qr_code, str):
            return False

        qr_code = qr_code.strip()

        # Check length
        if len(qr_code) < self.min_qr_length or len(qr_code) > self.max_qr_length:
            return False

        # Check for valid characters (URLs and typical QR content)
        # Added: & % , for URL parameters and encoding
        if not all(c.isalnum() or c in '-_=+/:?.{}[]()&%,' for c in qr_code):
            return False

        return True
    
    def manual_scan(self, qr_code: str) -> bool:
        """Manually input a QR code for testing."""
        try:
            if not self._validate_qr_format(qr_code):
                logger.warning(f"Invalid QR code format: {qr_code}")
                return False
            
            scan_event = QRScanEvent(
                timestamp=time.time(),
                qr_code=qr_code.strip(),
                source="manual"
            )
            
            logger.info(f"Manual QR scan: {scan_event.qr_code}")
            
            # Process the scan event (same as _process_scan)
            self._process_scan(scan_event.qr_code)
            
            return True
            
        except Exception as e:
            logger.error(f"Error in manual scan: {e}")
            return False
    
    def check_for_scans(self):
        """
        Check for QR scans from file or handle partial scan timeouts.
        """
        # Check for QR code in file
        qr_code = self._read_qr_from_file()
        if qr_code:
            self._process_scan(qr_code)
        
        # Check for timeout on partial scans (thread-safe check)
        current_time = time.time()
        if self._current_scan and (current_time - self._last_char_time > self.scan_timeout):
            logger.debug("Clearing timed-out partial QR scan")
            self._current_scan = ""
    
    def get_status(self) -> Dict[str, Any]:
        """Get scanner status."""
        return {
            "running": self._running,
            "has_evdev": HAS_EVDEV,
            "scan_enabled": self.scan_enabled,
            "callbacks_registered": len(self._scan_callbacks),
            "current_scan_length": len(self._current_scan),
            "device_path": self.device_path,
            "qr_file_exists": self.qr_file_path.exists(),
            "scanner_thread_active": self._scanner_thread is not None and self._scanner_thread.is_alive() if self._scanner_thread else False
        }
    
    @property
    def is_running(self) -> bool:
        """Check if scanner is running."""
        return self._running