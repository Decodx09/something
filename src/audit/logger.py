"""
Audit logging system for the Container Return System
"""

import logging
from datetime import datetime
from typing import Optional

from ..database.connection import DatabaseConnection, get_database
from ..database.models import LogType, AuditLogCreate
from ..database.crud import AuditLogCRUD
from ..config.config_manager import get_config


class AuditLogger:
    """Audit logger with database backend"""
    
    def __init__(self, db: Optional[DatabaseConnection] = None):
        self.logger = logging.getLogger("audit")
        
        if db is None:
            settings = get_config()
            db = get_database(settings.database_url)
        
        self.db = db
        self.audit_crud = AuditLogCRUD(db)
    
    def _log_to_database(self, log_type: LogType, description: str, 
                        container_id: Optional[str] = None, 
                        is_offline: bool = False) -> None:
        """Log audit entry to database"""
        try:
            audit_log = AuditLogCreate(
                type=log_type,
                description=description,
                is_offline_action=is_offline,
                container_id=container_id
            )
            
            self.audit_crud.create_log(audit_log)
            
            # Also log to application logger for immediate visibility
            log_level = logging.ERROR if log_type == LogType.ERROR else logging.INFO
            self.logger.log(
                log_level,
                f"[{log_type.value}] {description} "
                f"(Container: {container_id or 'N/A'}, Offline: {is_offline})"
            )
            
        except Exception as e:
            # If database logging fails, at least log to application logger
            if "FOREIGN KEY constraint failed" in str(e) and container_id:
                # Try again without container_id if foreign key constraint fails
                try:
                    audit_log = AuditLogCreate(
                        type=log_type,
                        description=f"{description} (Container ID: {container_id} - not found in DB)",
                        is_offline_action=is_offline,
                        container_id=None
                    )
                    self.audit_crud.create_log(audit_log)
                    self.logger.warning(f"Logged audit entry without container reference due to FK constraint")
                    return
                except Exception:
                    pass
            
            self.logger.error(f"Failed to log audit entry to database: {e}")
            self.logger.log(
                logging.ERROR if log_type == LogType.ERROR else logging.INFO,
                f"[{log_type.value}] {description} "
                f"(Container: {container_id or 'N/A'}, Offline: {is_offline})"
            )
    
    def log_return_valid(self, container_id: str, description: str, 
                        is_offline: bool = False) -> None:
        """Log successful container return"""
        self._log_to_database(
            LogType.RETURN_VALID,
            description,
            container_id,
            is_offline
        )
    
    def log_return_invalid(self, container_id: str, description: str, 
                          is_offline: bool = False) -> None:
        """Log invalid container return attempt"""
        self._log_to_database(
            LogType.RETURN_INVALID,
            description,
            container_id,
            is_offline
        )
    
    def log_info(self, description: str, container_id: Optional[str] = None, 
                is_offline: bool = False) -> None:
        """Log informational audit entry"""
        self._log_to_database(
            LogType.INFO,
            description,
            container_id,
            is_offline
        )
    
    def log_error(self, description: str, container_id: Optional[str] = None, 
                 is_offline: bool = False) -> None:
        """Log error audit entry"""
        self._log_to_database(
            LogType.ERROR,
            description,
            container_id,
            is_offline
        )
    
    # Convenience methods for common audit scenarios
    
    def log_system_startup(self, version: str) -> None:
        """Log system startup"""
        self.log_info(f"Container Return System started - Version: {version}")
    
    def log_system_shutdown(self, reason: str = "Normal shutdown") -> None:
        """Log system shutdown"""
        self.log_info(f"Container Return System shutdown - Reason: {reason}")
    
    def log_database_init(self) -> None:
        """Log database initialization"""
        self.log_info("Database initialized successfully")
    
    def log_database_error(self, error: str) -> None:
        """Log database error"""
        self.log_error(f"Database error: {error}")
    
    def log_uart_connection(self, port: str, status: str) -> None:
        """Log UART connection status"""
        self.log_info(f"UART connection {status} on port {port}")
    
    def log_uart_error(self, error: str) -> None:
        """Log UART communication error"""
        self.log_error(f"UART communication error: {error}")
    
    def log_api_sync_start(self) -> None:
        """Log API sync start"""
        self.log_info("API synchronization started")
    
    def log_api_sync_success(self, synced_count: int) -> None:
        """Log successful API sync"""
        self.log_info(f"API synchronization completed - {synced_count} items synced")
    
    def log_api_sync_failure(self, error: str) -> None:
        """Log API sync failure"""
        self.log_error(f"API synchronization failed: {error}", is_offline=True)
    
    def log_container_scanned(self, qr_code: str) -> None:
        """Log container QR code scan"""
        self.log_info(f"Container QR code scanned: {qr_code}")
    
    def log_qr_scan(self, container_id: str, source: str = "usb") -> None:
        """Log QR scan event"""
        self.log_info(f"QR code scanned from {source}", container_id)
    
    def log_container_validated(self, container_id: str, qr_code: str) -> None:
        """Log container validation success"""
        self.log_return_valid(
            container_id,
            f"Container validated successfully - QR: {qr_code}"
        )
    
    def log_container_rejected(self, qr_code: str, reason: str, 
                             container_id: Optional[str] = None) -> None:
        """Log container rejection"""
        self.log_return_invalid(
            container_id or "unknown",
            f"Container rejected - QR: {qr_code}, Reason: {reason}"
        )
    
    def log_container_expired(self, container_id: str, qr_code: str, 
                            due_date: datetime) -> None:
        """Log expired container attempt"""
        self.log_return_invalid(
            container_id,
            f"Expired container - QR: {qr_code}, Due: {due_date.isoformat()}"
        )
    
    def log_container_not_returnable(self, container_id: str, qr_code: str) -> None:
        """Log non-returnable container attempt"""
        self.log_return_invalid(
            container_id,
            f"Non-returnable container - QR: {qr_code}"
        )
    
    def log_container_not_found(self, qr_code: str) -> None:
        """Log container not found in database"""
        self.log_return_invalid(
            "unknown",
            f"Container not found in database - QR: {qr_code}"
        )
    
    def log_sequence_started(self, sequence_type: str) -> None:
        """Log sequence start"""
        self.log_info(f"Sequence started: {sequence_type}")
    
    def log_sequence_completed(self, sequence_type: str, duration: float) -> None:
        """Log sequence completion"""
        self.log_info(f"Sequence completed: {sequence_type} ({duration:.2f}s)")
    
    def log_sequence_failed(self, sequence_type: str, error: str) -> None:
        """Log sequence failure"""
        self.log_error(f"Sequence failed: {sequence_type} - {error}")
    
    def log_hardware_status(self, component: str, status: str) -> None:
        """Log hardware component status"""
        self.log_info(f"Hardware status - {component}: {status}")
    
    def log_hardware_error(self, component: str, error: str) -> None:
        """Log hardware error"""
        self.log_error(f"Hardware error - {component}: {error}")
    
    def log_safe_mode_entered(self, reason: str) -> None:
        """Log safe mode activation"""
        self.log_error(f"Safe mode activated - Reason: {reason}")
    
    def log_safe_mode_exited(self) -> None:
        """Log safe mode deactivation"""
        self.log_info("Safe mode deactivated")
    
    def log_device_status_update(self, field: str, old_value: str, new_value: str) -> None:
        """Log device status update"""
        self.log_info(f"Device status updated - {field}: {old_value} -> {new_value}")
    
    def log_maintenance_mode(self, enabled: bool) -> None:
        """Log maintenance mode change"""
        status = "enabled" if enabled else "disabled"
        self.log_info(f"Maintenance mode {status}")
    
    def log_configuration_change(self, setting: str, old_value: str, new_value: str) -> None:
        """Log configuration change"""
        self.log_info(f"Configuration changed - {setting}: {old_value} -> {new_value}")
    
    def log_offline_mode_entered(self, reason: str) -> None:
        """Log offline mode activation"""
        self.log_info(f"Offline mode activated - Reason: {reason}", is_offline=True)
    
    def log_offline_mode_exited(self) -> None:
        """Log offline mode deactivation"""
        self.log_info("Offline mode deactivated")
    
    def log_cleanup_completed(self, deleted_count: int) -> None:
        """Log audit log cleanup"""
        self.log_info(f"Audit log cleanup completed - {deleted_count} entries deleted")

    def log_security_event(self, event_type: str, description: str,
                          details: Optional[dict] = None) -> None:
        """Log security-related events (fraud attempts, unauthorized access, etc.)"""
        detail_str = ""
        if details:
            detail_str = f" - Details: {details}"
        self.log_error(f"Security Event [{event_type}]: {description}{detail_str}")


# Global audit logger instance
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """Get global audit logger instance"""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


def initialize_audit_logger(db: Optional[DatabaseConnection] = None) -> AuditLogger:
    """Initialize audit logger with specific database connection"""
    global _audit_logger
    _audit_logger = AuditLogger(db)
    return _audit_logger


# Convenience functions for common audit operations
def audit_return_valid(container_id: str, description: str, is_offline: bool = False) -> None:
    """Convenience function for logging valid returns"""
    get_audit_logger().log_return_valid(container_id, description, is_offline)


def audit_return_invalid(container_id: str, description: str, is_offline: bool = False) -> None:
    """Convenience function for logging invalid returns"""
    get_audit_logger().log_return_invalid(container_id, description, is_offline)


def audit_info(description: str, container_id: Optional[str] = None, is_offline: bool = False) -> None:
    """Convenience function for logging info"""
    get_audit_logger().log_info(description, container_id, is_offline)


def audit_error(description: str, container_id: Optional[str] = None, is_offline: bool = False) -> None:
    """Convenience function for logging errors"""
    get_audit_logger().log_error(description, container_id, is_offline) 