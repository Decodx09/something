"""
Main Application Module

Entry point for the Raspberry Pi Container Return System.
Simple initialization and execution.
"""

import argparse
import logging
import os
import signal
import sys
import time
from typing import Optional
from .config.config_manager import get_config, ConfigManager
from .config.logging_config import setup_logging
from .config.validator import validate_config
from .database.connection import get_database, DatabaseError
from .database.crud import DatabaseManager
from .audit.logger import initialize_audit_logger, AuditLogger
from .uart.uart import UART
from .qr.scanner import QRScanner
from .qr.processor import QRProcessor
from .api.service import APIService


class ContainerReturnSystem:
    """Main application class for the Container Return System"""
    
    def __init__(self) -> None:
        self.config: Optional[ConfigManager] = None
        self.logger: Optional[logging.Logger] = None
        self.audit_logger: Optional[AuditLogger] = None
        self.db_manager: Optional[DatabaseManager] = None
        self.uart_manager: Optional[UART] = None
        self.qr_scanner: Optional[QRScanner] = None
        self.qr_processor: Optional[QRProcessor] = None
        self.api_service: Optional[APIService] = None
        self.shutdown_requested: bool = False
        self.device_inactive: bool = False  # Track device inactive state
        self.device_secure_mode: bool = False  # Track secure mode state
    
    def setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown"""
        def signal_handler(signum, frame):
            _ = signum, frame  # Unused parameters
            print("Shutdown signal received...")
            self.shutdown_requested = True
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    def load_configuration(self, debug: bool = False) -> None:
        """Load application configuration"""
        try:
            # Set debug environment variable if requested
            if debug:
                import os
                os.environ['DEBUG'] = 'true'
                os.environ['LOG_LEVEL'] = 'DEBUG'
            
            # Validate configuration
            if not validate_config():
                raise RuntimeError("Configuration validation failed")
            
            self.config = get_config()
        except Exception as e:
            print(f"Configuration error: {e}")
            sys.exit(1)
    
    def setup_logging(self) -> None:
        """Setup logging system"""
        if not self.config:
            raise RuntimeError("Configuration not loaded")
        
        log_config = {
            "log_level": self.config.log_level,
            "log_file": self.config.log_file,
            "debug": self.config.debug
        }
        setup_logging(log_config)
        self.logger = logging.getLogger(__name__)
        
        if self.logger:
            self.logger.info("Logging system initialized")
    
    def initialize_database(self) -> None:
        """Initialize database"""
        if not self.config:
            raise RuntimeError("Configuration not loaded")
        
        try:
            db = get_database(self.config.database_url)
            self.db_manager = DatabaseManager(db)
            self.db_manager.initialize()
            self.audit_logger = initialize_audit_logger(db)
            
            if self.logger:
                self.logger.info("Database initialized")
                
        except DatabaseError as e:
            print(f"Database error: {e}")
            sys.exit(1)
    
    def initialize_uart(self) -> None:
        """Initialize UART communication"""
        try:
            if not self.config:
                raise RuntimeError("Configuration not loaded")
            
            self.uart_manager = UART(
                port=self.config.uart_port,
                baudrate=self.config.uart_baudrate,
                db_manager=self.db_manager,
                debug_mode=self.config.debug
            )
            
            if self.uart_manager.start():
                if self.logger:
                    self.logger.info("UART initialized")
            else:
                raise RuntimeError("Failed to start UART")
                
        except Exception as e:
            print(f"UART error: {e}")
            sys.exit(1)
    
    def initialize_components(self) -> None:
        """Initialize all system components"""
        try:
            # Initialize core components
            self.qr_processor = QRProcessor(self.db_manager)

            # Try to initialize QR scanner (requires evdev on Linux)
            try:
                self.qr_scanner = QRScanner(
                    uart_manager=self.uart_manager,
                    audit_logger=self.audit_logger,
                    device_path=self.config.qr_scanner_device
                )

                # Set up QR scanner callback to process scanned codes
                if self.qr_scanner:
                    self.qr_scanner.add_scan_callback(self._handle_qr_scan)
                    self.qr_scanner.start_scanning()

                if self.logger:
                    self.logger.info("QR scanner initialized successfully")
            except RuntimeError as e:
                # QR scanner not available (likely Windows/dev environment)
                self.qr_scanner = None
                if self.logger:
                    self.logger.warning(f"QR scanner not available: {e}")
                    self.logger.info("QR file-based scanning will still work for testing")
            
            # Initialize API service
            if self.config and self.db_manager:
                self.api_service = APIService(self.config, self.db_manager)
                # Set device status callback
                self.api_service.set_device_status_callback(self._on_device_status_change)
                # Set secure mode callback
                self.api_service.set_secure_mode_callback(self._on_secure_mode_change)
            
            # Set API service, audit logger, and QR processor on UART manager
            if self.uart_manager:
                if self.api_service:
                    self.uart_manager.set_api_service(self.api_service)
                if self.audit_logger:
                    self.uart_manager.set_audit_logger(self.audit_logger)
                if self.qr_processor:
                    self.uart_manager.qr_processor = self.qr_processor
                # Set device inactive callback
                self.uart_manager.set_device_inactive_callback(lambda: self.device_inactive or self.device_secure_mode)
            
            # UART initialization complete
            
            # Check initial device status and set inactive mode if needed
            self._initialize_device_status()
            
            # Check initial secure mode status
            self._initialize_secure_mode_status()
            
            if self.logger:
                self.logger.info("All components initialized")
                
        except Exception as e:
            if self.logger:
                self.logger.error(f"Component initialization failed: {e}")
            sys.exit(1)
    
    def run_main_loop(self) -> None:
        """Simple main application loop"""
        if self.logger:
            self.logger.info("Starting main loop")
        
        loop_counter = 0
        
        while not self.shutdown_requested:
            try:
                # Process UART messages and handle sequences
                if self.uart_manager:
                    self.uart_manager.process_messages()
                
                # Check API operations (healthcheck and sync)
                if self.api_service:
                    self.api_service.check_and_run()
                
                # QR scanner uses evdev HID device access with file-based communication
                # check_for_scans() reads from file and handles timeouts
                if self.qr_scanner:
                    self.qr_scanner.check_for_scans()
                else:
                    # Fallback: directly check QR file for testing without evdev
                    self._check_qr_file_fallback()
                
                # Update device status every 300 seconds
                if self.db_manager and loop_counter % 300 == 0:
                    self.db_manager.device_status.update_seen_time()
                
                # Simple loop with 1 second interval
                time.sleep(1)
                loop_counter += 1
                
            except KeyboardInterrupt:
                self.shutdown_requested = True
                break
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Main loop error: {e}")
                break
        
        if self.logger:
            self.logger.info("Main loop ended")
    
    def reset_system(self) -> None:
        """Reset system to idle state"""
        if self.uart_manager:
            self.uart_manager.reset_to_idle()
        
        if self.logger:
            self.logger.info("System reset to idle state")
    
    def _handle_qr_scan(self, scan_event) -> None:
        """Handle QR code scan event from USB scanner (non-sequence cases only)."""
        try:
            if self.logger:
                self.logger.info(f"QR code scanned outside sequence: {scan_event.qr_code}")
            
            # Process for debugging/testing when not in sequence
            if self.qr_processor:
                result = self.qr_processor.process_qr_code(scan_event.qr_code)
                
                # Check for fraud attempts
                if result.is_fraud_attempt or result.validation.value == "fraud_attempt":
                    if self.logger:
                        self.logger.warning(f"Fraud attempt detected: {result.error_message}")
                    # Log fraud attempt to audit system
                    if self.audit_logger:
                        self.audit_logger.log_security_event(
                            event_type="fraud_attempt",
                            description=f"QR fraud attempt detected outside sequence: {result.error_message}",
                            details={
                                "qr_code": scan_event.qr_code,
                                "validation_result": result.validation.value,
                                "error": result.error_message
                            }
                        )
                elif result.validation.value == "valid" and result.container_id:
                    if self.logger:
                        self.logger.info(f"Valid container scanned: {result.container_id}")
                else:
                    if self.logger:
                        self.logger.warning(f"Invalid QR code: {result.error_message}")
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error handling QR scan: {e}")

    def _check_qr_file_fallback(self) -> None:
        """Simple QR file check for dev/testing without evdev."""
        try:
            from pathlib import Path
            qr_file = Path("qr_scan_data.txt")
            if qr_file.exists():
                qr_code = qr_file.read_text().strip()
                qr_file.unlink()
                if qr_code and self.qr_processor:
                    result = self.qr_processor.process_qr_code(qr_code)
                    if self.logger:
                        self.logger.info(f"QR: {qr_code} -> {result.validation.value}")
                    # Pass to UART if waiting
                    if self.uart_manager and self.uart_manager._waiting_for_qr:
                        self.uart_manager._container_qr_code = qr_code
                        self.uart_manager._waiting_for_qr = False
        except Exception:
            pass

    def shutdown(self) -> None:
        """Clean shutdown"""
        print("Shutting down...")
        
        if self.qr_scanner:
            self.qr_scanner.stop_scanning()
        
        if self.uart_manager:
            self.uart_manager.turn_all_lights_off()
        
        if self.uart_manager:
            self.uart_manager.stop()
        
        if self.audit_logger:
            self.audit_logger.log_system_shutdown("Normal shutdown")
        
        print("Shutdown complete")
    
    def print_config(self) -> None:
        """Print current environment variables and configuration"""
        print("=== Container Return System Configuration ===")
        print()
        
        # Print environment variables
        print("Environment Variables:")
        print("-" * 40)
        env_vars = [
            'RASPBERRY_NAME',
            'DEVICE_NAME', 
            'API_KEY',
            'RASPBERRY_API_KEY',
            'DATABASE_URL',
            'UART_PORT',
            'UART_BAUDRATE',
            'LOG_LEVEL',
            'LOG_FILE',
            'DEBUG',
            'APP_VERSION'
        ]
        
        for var in env_vars:
            value = os.getenv(var, 'NOT SET')
            # Mask sensitive values
            if 'API_KEY' in var and value != 'NOT SET':
                value = '*' * min(len(value), 8) + '...' if len(value) > 8 else '*' * len(value)
            print(f"{var:<20} = {value}")
        
        print()
        
        print()
        print("=" * 50)
    
    def run(self, debug: bool = False) -> int:
        """Run the complete application"""
        try:
            # Setup
            self.setup_signal_handlers()
            self.load_configuration(debug=debug)
            self.setup_logging()
            
            # Initialize system
            self.initialize_database()
            self.initialize_uart()
            self.initialize_components()
            
            if self.audit_logger and self.config:
                self.audit_logger.log_system_startup(f"Container Return System v{self.config.app_version}")
            
            # Run
            self.run_main_loop()
            
            return 0
            
        except Exception as e:
            print(f"Application error: {e}")
            return 1
        finally:
            self.shutdown()
    
    def _on_device_status_change(self, active: bool) -> None:
        """Handle device active status change from healthcheck.
        
        Args:
            active: True if device is active, False if inactive
        """
        if self.logger:
            self.logger.info(f"Device status change: active={active}")
        
        if not active:
            # Device became inactive - enter inactive mode
            self._enter_inactive_mode()
        else:
            # Device became active - exit inactive mode
            self._exit_inactive_mode()
    
    def _enter_inactive_mode(self) -> None:
        """Enter inactive mode: turn all lights red and stop message processing."""
        if self.logger:
            self.logger.warning("Entering inactive mode - device is not active")
        
        self.device_inactive = True
        
        # Turn all lights red and block doors
        if self.uart_manager:
            try:
                self.logger.info("Setting all lights to red and blocking doors due to inactive status") if self.logger else None
                # Set both cover and container lights to red
                self.uart_manager.set_cover_light_red()
                self.uart_manager.set_container_light_red()
                # Block doors
                self.uart_manager.block_doors()
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Failed to set red lights and block doors: {e}")
        
        # Disable QR scanning
        if self.qr_scanner:
            self.qr_scanner.disable_scanning()
            if self.logger:
                self.logger.info("QR scanning disabled due to inactive status")
        
        # Log audit event
        if self.audit_logger:
            self.audit_logger.log_info("Device entered inactive mode - all operations suspended")
    
    def _exit_inactive_mode(self) -> None:
        """Exit inactive mode: turn off lights and resume normal operation."""
        if self.logger:
            self.logger.info("Exiting inactive mode - device is now active")
        
        self.device_inactive = False
        
        # Turn off all lights and unblock doors
        if self.uart_manager:
            try:
                self.logger.info("Turning off all lights and unblocking doors - resuming normal operation") if self.logger else None
                self.uart_manager.turn_all_lights_off()
                # Unblock doors
                self.uart_manager.unblock_doors()
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Failed to turn off lights and unblock doors: {e}")
        
        # Re-enable QR scanning
        if self.qr_scanner:
            self.qr_scanner.enable_scanning()
            if self.logger:
                self.logger.info("QR scanning re-enabled - device is active")
        
        # Log audit event
        if self.audit_logger:
            self.audit_logger.log_info("Device exited inactive mode - normal operations resumed")
    
    def _initialize_device_status(self) -> None:
        """Initialize device status on startup based on database value."""
        if not self.db_manager:
            if self.logger:
                self.logger.warning("No database manager available for device status check")
            return
        
        try:
            # Get current device status from database
            device_status = self.db_manager.device_status.get_status()
            
            if device_status:
                if self.logger:
                    self.logger.info(f"Found existing device status - active: {device_status.active}")
                
                if not device_status.active:
                    # Device is inactive in database - enter inactive mode immediately
                    if self.logger:
                        self.logger.warning("Device is inactive according to database - entering inactive mode")
                    self._enter_inactive_mode()
                else:
                    # Device is active - ensure we're in active mode
                    if self.logger:
                        self.logger.info("Device is active according to database")
                    self.device_inactive = False
                    
                    # Initialize the API service's last active status
                    if self.api_service:
                        self.api_service._last_active_status = True
            else:
                if self.logger:
                    self.logger.info("No existing device status found - device will be active by default")
                self.device_inactive = False
                
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error checking initial device status: {e}")
            # Default to active mode on error
            self.device_inactive = False
    
    def _on_secure_mode_change(self, secure_mode: bool) -> None:
        """Handle secure mode status change from API service.
        
        Args:
            secure_mode: True if device should be in secure mode, False otherwise
        """
        if self.logger:
            self.logger.info(f"Secure mode status change: secure_mode={secure_mode}")
        
        if secure_mode:
            # Device entered secure mode - activate security measures
            self._enter_secure_mode()
        else:
            # Device exited secure mode - return to normal operation
            self._exit_secure_mode()
    
    def _enter_secure_mode(self) -> None:
        """Enter secure mode: turn all lights red and block doors due to server disconnection."""
        if self.logger:
            self.logger.warning("Entering secure mode - server disconnected for 2+ days")
        
        self.device_secure_mode = True
        
        # Turn all lights red and block doors
        if self.uart_manager:
            try:
                self.logger.info("Setting all lights to red and blocking doors due to secure mode") if self.logger else None
                # Set both cover and container lights to red
                self.uart_manager.set_cover_light_red()
                self.uart_manager.set_container_light_red()
                # Block doors
                self.uart_manager.block_doors()
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Failed to set red lights and block doors in secure mode: {e}")
        
        # Disable QR scanning
        if self.qr_scanner:
            self.qr_scanner.disable_scanning()
            if self.logger:
                self.logger.info("QR scanning disabled due to secure mode")
        
        # Log audit event
        if self.audit_logger:
            self.audit_logger.log_info("Device entered secure mode - server disconnected for 2+ days")
    
    def _exit_secure_mode(self) -> None:
        """Exit secure mode: turn off lights and resume normal operation."""
        if self.logger:
            self.logger.info("Exiting secure mode - server connection restored")
        
        self.device_secure_mode = False
        
        # Only turn off lights and unblock doors if not in inactive mode
        if not self.device_inactive:
            if self.uart_manager:
                try:
                    self.logger.info("Turning off all lights and unblocking doors - exiting secure mode") if self.logger else None
                    self.uart_manager.turn_all_lights_off()
                    # Unblock doors
                    self.uart_manager.unblock_doors()
                except Exception as e:
                    if self.logger:
                        self.logger.error(f"Failed to turn off lights and unblock doors when exiting secure mode: {e}")
            
            # Re-enable QR scanning
            if self.qr_scanner:
                self.qr_scanner.enable_scanning()
                if self.logger:
                    self.logger.info("QR scanning re-enabled - exiting secure mode")
        else:
            if self.logger:
                self.logger.info("Device still in inactive mode - keeping restrictions in place")
        
        # Log audit event
        if self.audit_logger:
            self.audit_logger.log_info("Device exited secure mode - server connection restored")
    
    def _initialize_secure_mode_status(self) -> None:
        """Initialize secure mode status on startup based on database value."""
        if not self.db_manager:
            if self.logger:
                self.logger.warning("No database manager available for secure mode status check")
            return
        
        try:
            # Get current device status from database
            device_status = self.db_manager.device_status.get_status()
            
            if device_status and device_status.is_in_safe_mode:
                if self.logger:
                    self.logger.warning("Device is in secure mode according to database - entering secure mode")
                self._enter_secure_mode()
            else:
                if self.logger:
                    self.logger.info("Device is not in secure mode according to database")
                self.device_secure_mode = False
                
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error checking initial secure mode status: {e}")
            # Default to normal mode on error
            self.device_secure_mode = False


def main() -> int:
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Container Return System")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--check-config", action="store_true", help="Print current environment variables and configuration")
    
    args = parser.parse_args()
    
    app = ContainerReturnSystem()
    
    if args.check_config:
        app.print_config()
        return 0
    
    return app.run(debug=args.debug)


if __name__ == "__main__":
    sys.exit(main()) 