"""
Simple API service for periodic healthcheck and sync operations
"""

import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

from .client import APIClient
from ..database.models import DeviceStatus, DeviceStatusUpdate, Container, AuditLog, ContainerCreate

logger = logging.getLogger(__name__)


class APIService:
    """Simple service for API communication with periodic checks."""
    
    def __init__(self, config_manager, db_manager):
        self.config = config_manager
        self.db = db_manager
        self.client = APIClient(config_manager)
        
        # Get intervals from configuration
        self.healthcheck_interval = int(self.config.get('HEALTHCHECK_INTERVAL', 300))  # 5 min default
        self.sync_interval = int(self.config.get('SYNC_INTERVAL', 600))  # 10 min default
        
        # Track last execution times
        self._last_healthcheck = 0
        self._last_sync = 0
        self._last_sync_at = None
        self._initial_sync_done = False
        
        # Device status callback
        self._device_status_callback = None
        self._last_active_status = None
        
        # Secure mode tracking
        self._secure_mode_callback = None
        self._last_secure_mode_status = None
        self.SECURE_MODE_THRESHOLD = timedelta(days=2)  # 2 days without server connection
        
        logger.info(f"API service initialized - Health: {self.healthcheck_interval}s, Sync: {self.sync_interval}s")
    
    def check_and_run(self):
        """Check if any API operations need to run and execute them."""
        current_time = time.time()
        
        # Do initial sync first
        if not self._initial_sync_done:
            self._do_initial_sync()
            self._initial_sync_done = True
            # Prevent immediate regular sync after initial sync
            self._last_sync = current_time
        
        # Check if healthcheck is due
        if current_time - self._last_healthcheck >= self.healthcheck_interval:
            try:
                self._do_healthcheck()
                self._last_healthcheck = current_time
            except Exception as e:
                logger.error(f"Healthcheck error: {e}")
        
        # Check if sync is due
        if current_time - self._last_sync >= self.sync_interval:
            try:
                self._do_sync()
                self._last_sync = current_time
            except Exception as e:
                logger.error(f"Sync error: {e}")
    
    def _do_healthcheck(self):
        """Perform healthcheck."""
        logger.debug("Sending healthcheck")
        
        # Get device status
        device_status = self.db.device_status.get_status()
        if not device_status:
            # Create default status
            version = self.config.get('APP_VERSION', '1.0.0')
            update = DeviceStatusUpdate(
                version=version,
                update_failures=0,
                last_seen_at=datetime.now(timezone.utc)
            )
            device_status = self.db.device_status.update_status(update)
        
        # Send healthcheck
        try:
            response = self.client.healthcheck(
                version=device_status.version,
                update_failures=device_status.update_failures
            )
            
            if response.get('success'):
                logger.debug("Healthcheck successful")
                
                # Extract data from response
                data = response.get('data', {})
                active = data.get('active')
                
                # Update device status with server response - successful connection resets secure mode
                update_fields = {
                    'last_seen_at': datetime.now(timezone.utc),
                    'is_in_safe_mode': False  # Reset secure mode on successful connection
                }
                
                if active is not None:
                    active_bool = bool(active)
                    update_fields['active'] = active_bool
                    logger.info(f"Device active status updated from server: {active}")
                    
                    # Check if status changed and trigger callback
                    if self._last_active_status is not None and self._last_active_status != active_bool:
                        if self._device_status_callback:
                            try:
                                self._device_status_callback(active_bool)
                            except Exception as e:
                                logger.error(f"Error in device status callback: {e}")
                    
                    self._last_active_status = active_bool
                
                update = DeviceStatusUpdate(**update_fields)
                self.db.device_status.update_status(update)
            else:
                logger.warning(f"Healthcheck failed: {response}")
                
        except Exception as e:
            logger.error(f"Healthcheck request failed: {e}")
            # Increment failure count
            if device_status:
                update = DeviceStatusUpdate(update_failures=device_status.update_failures + 1)
                self.db.device_status.update_status(update)
        
        # Check secure mode status after healthcheck (regardless of success/failure)
        self._check_secure_mode()
    
    def _do_initial_sync(self):
        """Do initial sync on startup - delete local data and get fresh data from server."""
        logger.info("Performing initial sync - deleting local data and fetching from server")
        
        try:
            # Delete all local audit logs and containers first
            self.db.audit_logs.delete_all()
            self.db.containers.delete_all()
            logger.info("Deleted all local containers and audit logs")
            
            # Send empty data to server but get latest containers back
            response = self.client.sync(logs=[], containers=[])
            
            if response.get('success'):
                # Update containers from server response  
                containers_response = response.get('data', [])
                self._update_containers(containers_response)
                
                # Update last sync time
                self._last_sync_at = datetime.now(timezone.utc)
                update = DeviceStatusUpdate(last_sync_at=self._last_sync_at)
                self.db.device_status.update_status(update)
                
                logger.info(f"Initial sync complete - received {len(containers_response)} containers from server")
            else:
                logger.error(f"Initial sync failed: {response}")
                
        except Exception as e:
            logger.error(f"Initial sync error: {e}")
    
    def _do_sync(self):
        """Perform periodic sync."""
        logger.debug("Performing sync")
        
        # Get last sync time from database (before updating it)
        device_status = self.db.device_status.get_status()
        if device_status:
            # Device status exists - always use lastSyncAt (even on restart)
            old_last_sync_at = device_status.last_sync_at
            logger.debug(f"Syncing logs since last sync: {old_last_sync_at}")
        else:
            # No device status found - this is the very first run
            # Use Unix epoch to get ALL existing logs
            old_last_sync_at = datetime.fromtimestamp(0, tz=timezone.utc)
            logger.info("No device status found - fetching all existing audit logs (first run)")
        
        # Capture sync time after determining old sync time but before getting data
        # This ensures no logs created during sync are missed
        new_sync_time = datetime.now(timezone.utc)
        
        # Get data to sync - only containers/logs updated since last sync
        containers = self.db.containers.get_since(old_last_sync_at)
        logs = self.db.audit_logs.get_logs_since(old_last_sync_at)
        
        containers_data = [self._container_to_dict(c) for c in containers]
        # Filter out logs with None container_id (system logs, etc.)
        filtered_logs = [log for log in logs if log.container_id is not None]
        logs_data = [self._log_to_dict(log) for log in filtered_logs]
        
        logger.debug(f"Syncing {len(containers_data)} containers and {len(logs_data)} logs since {old_last_sync_at}")
        
        try:
            response = self.client.sync(logs=logs_data, containers=containers_data)
            
            if response.get('success'):
                # Delete synced logs first (before updating containers)
                for log in logs:
                    self.db.audit_logs.delete_log(log.id)
                
                # Update containers from server response
                containers_response = response.get('data', [])
                self._update_containers(containers_response)
                
                # Update last sync time in device status (use captured time)
                update = DeviceStatusUpdate(last_sync_at=new_sync_time)
                self.db.device_status.update_status(update)
                
                logger.info(f"Sync complete - sent {len(containers_data)} containers, {len(logs_data)} logs")
            else:
                logger.warning(f"Sync failed: {response}")
                
        except Exception as e:
            logger.error(f"Sync request failed: {e}")
    
    def _container_to_dict(self, container: Container) -> Dict[str, Any]:
        """Convert container to dict for API."""
        # Format timestamp as required by server: YYYY-MM-DD HH:MM:SS.mmm+00
        formatted_timestamp = container.updated_at.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3] + '+00'
        return {
            "id": container.id,
            "isReturnable": container.is_returnable,
            "updatedAt": formatted_timestamp
        }
    
    def _log_to_dict(self, log: AuditLog) -> Dict[str, Any]:
        """Convert audit log to dict for API."""
        # Format timestamp as required by server: YYYY-MM-DD HH:MM:SS.mmm+00
        formatted_timestamp = log.created_at.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3] + '+00'
        return {
            "type": log.type.value,
            "description": log.description,
            "isOfflineAction": log.is_offline_action,
            "containerId": log.container_id,
            "createdAt": formatted_timestamp
        }
    
    def _update_containers(self, containers_data: List[Dict[str, Any]]):
        """Replace all containers with server data."""
        try:
            # Clear existing containers
            self.db.containers.delete_all()
            logger.debug("Cleared all existing containers")
            
            # Insert all new containers from server
            for container_data in containers_data:
                container_id = container_data.get('id')
                qr_code = container_data.get('qrCode', '')
                is_returnable = container_data.get('isReturnable', True)
                
                # Parse due date from DateTime field
                due_date = None
                if 'dueTime' in container_data:
                    try:
                        due_date = datetime.fromisoformat(
                            container_data['dueTime'].replace('Z', '+00:00')
                        )
                    except ValueError:
                        logger.warning(f"Invalid dueTime format for container {container_id}")
                
                if container_id and qr_code:
                    container_create = ContainerCreate(
                        qr_code=qr_code,
                        is_returnable=is_returnable,
                        due_date=due_date
                    )
                    self.db.containers.create_with_id(container_id, container_create)
            
            logger.info(f"Replaced containers with {len(containers_data)} new records from server")
            
        except Exception as e:
            logger.error(f"Failed to replace containers: {e}")
            raise
    
    def validate_container(self, container_id: str) -> Optional[Dict[str, Any]]:
        """Validate container with server."""
        try:
            response = self.client.validate_container(container_id)
            if response.get('success'):
                return response.get('data')
            return None
        except Exception as e:
            logger.error(f"Container validation failed: {e}")
            return None
    
    def force_sync(self):
        """Force an immediate sync (useful for testing)."""
        logger.info("Forcing immediate sync")
        self._do_sync()
        self._last_sync = time.time()
    
    def force_healthcheck(self):
        """Force an immediate healthcheck (useful for testing)."""
        logger.info("Forcing immediate healthcheck")  
        self._do_healthcheck()
        self._last_healthcheck = time.time()
    
    def set_device_status_callback(self, callback):
        """Set callback function to be called when device active status changes.
        
        Args:
            callback: Function that takes a boolean (active status) as parameter
        """
        self._device_status_callback = callback
        logger.debug("Device status callback registered")
    
    def set_secure_mode_callback(self, callback):
        """Set callback function to be called when secure mode status changes.
        
        Args:
            callback: Function that takes a boolean (secure mode active) as parameter
        """
        self._secure_mode_callback = callback
        logger.debug("Secure mode callback registered")
    
    def _check_secure_mode(self):
        """Check if device should be in secure mode based on server connectivity."""
        try:
            # Get device status to check last successful server communication
            device_status = self.db.device_status.get_status()
            if not device_status:
                # No device status means we've never connected - don't enter secure mode
                should_be_secure = False
                logger.debug("No device status found - never connected to server, secure mode not activated")
            else:
                # Check if last_seen_at is older than 2 days
                now = datetime.now(timezone.utc)
                last_seen = device_status.last_seen_at
                if last_seen.tzinfo is None:
                    # Database returns timezone-naive datetime, assume UTC
                    last_seen = last_seen.replace(tzinfo=timezone.utc)
                
                time_since_last_seen = now - last_seen
                should_be_secure = time_since_last_seen > self.SECURE_MODE_THRESHOLD
                
                if should_be_secure:
                    logger.warning(f"Server disconnected for {time_since_last_seen} - entering secure mode")
                else:
                    logger.debug(f"Server last seen {time_since_last_seen} ago - secure mode not needed")
            
            # Update database secure mode status if changed
            current_secure_status = device_status.is_in_safe_mode if device_status else False
            if current_secure_status != should_be_secure:
                update = DeviceStatusUpdate(is_in_safe_mode=should_be_secure)
                self.db.device_status.update_status(update)
                logger.info(f"Updated secure mode status in database: {should_be_secure}")
            
            # Trigger callback if status changed
            if self._last_secure_mode_status is not None and self._last_secure_mode_status != should_be_secure:
                if self._secure_mode_callback:
                    try:
                        self._secure_mode_callback(should_be_secure)
                    except Exception as e:
                        logger.error(f"Error in secure mode callback: {e}")
            
            self._last_secure_mode_status = should_be_secure
            
        except Exception as e:
            logger.error(f"Error checking secure mode: {e}")