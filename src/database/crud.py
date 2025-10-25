"""
CRUD operations for the Container Return System database
"""

import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import uuid4

from .connection import DatabaseConnection, DatabaseError
from .models import (
    Container, DeviceStatus, AuditLog, LogType,
    ContainerCreate, DeviceStatusUpdate, AuditLogCreate
)

logger = logging.getLogger(__name__)


class ContainerCRUD:
    """CRUD operations for Container table"""
    
    def __init__(self, db: DatabaseConnection):
        self.db = db
    
    def create(self, container_data: ContainerCreate) -> Container:
        """Create a new container"""
        try:
            container_id = str(uuid4())
            now = datetime.utcnow().isoformat()
            
            with self.db.get_transaction() as conn:
                conn.execute("""
                    INSERT INTO Container (id, qrCode, isReturnable, dueDate, updatedAt)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    container_id,
                    container_data.qr_code,
                    1 if container_data.is_returnable else 0,
                    container_data.due_date.isoformat() if container_data.due_date else None,
                    now
                ))
            
            logger.info(f"Container created: {container_id}")
            return self.get_by_id(container_id) # type: ignore
            
        except Exception as e:
            logger.error(f"Failed to create container: {e}")
            raise DatabaseError(f"Container creation failed: {e}")
    
    def get_by_id(self, container_id: str) -> Optional[Container]:
        """Get container by ID"""
        try:
            row = self.db.fetchone(
                "SELECT * FROM Container WHERE id = ?",
                (container_id,)
            )
            
            if row:
                return Container(
                    id=row["id"],
                    qrCode=row["qrCode"],
                    isReturnable=bool(row["isReturnable"]),
                    dueDate=datetime.fromisoformat(row["dueDate"]) if row["dueDate"] else None,
                    updatedAt=datetime.fromisoformat(row["updatedAt"])
                )
            return None
            
        except Exception as e:
            logger.error(f"Failed to get container by ID {container_id}: {e}")
            raise DatabaseError(f"Container retrieval failed: {e}")
    
    def get_by_qr_code(self, qr_code: str) -> Optional[Container]:
        """Get container by QR code"""
        try:
            row = self.db.fetchone(
                "SELECT * FROM Container WHERE qrCode = ?",
                (qr_code,)
            )
            
            if row:
                return Container(
                    id=row["id"],
                    qrCode=row["qrCode"],
                    isReturnable=bool(row["isReturnable"]),
                    dueDate=datetime.fromisoformat(row["dueDate"]) if row["dueDate"] else None,
                    updatedAt=datetime.fromisoformat(row["updatedAt"])
                )
            return None
            
        except Exception as e:
            logger.error(f"Failed to get container by QR code {qr_code}: {e}")
            raise DatabaseError(f"Container retrieval failed: {e}")
    
    def update(self, container_id: str, updates: Dict[str, Any]) -> Optional[Container]:
        """Update container with given fields"""
        try:
            if not updates:
                return self.get_by_id(container_id)
            
            # Add updated timestamp
            updates["updatedAt"] = datetime.utcnow().isoformat()
            
            # Build dynamic update query
            set_clauses = []
            params = {}
            
            for field, value in updates.items():
                if field == "due_date" and value:
                    set_clauses.append("dueDate = :dueDate")
                    params["dueDate"] = value.isoformat() if isinstance(value, datetime) else value
                elif field == "is_returnable":
                    set_clauses.append("isReturnable = :isReturnable")
                    params["isReturnable"] = 1 if value else 0
                elif field == "qr_code":
                    set_clauses.append("qrCode = :qrCode")
                    params["qrCode"] = value
                elif field == "updatedAt":
                    set_clauses.append("updatedAt = :updatedAt")
                    params["updatedAt"] = value
            
            if not set_clauses:
                return self.get_by_id(container_id)
            
            params["id"] = container_id
            query = f"UPDATE Container SET {', '.join(set_clauses)} WHERE id = :id"
            
            with self.db.get_transaction() as conn:
                cursor = conn.execute(query, params)
                if cursor.rowcount == 0:
                    logger.warning(f"Container not found for update: {container_id}")
                    return None
            
            logger.info(f"Container updated: {container_id}")
            return self.get_by_id(container_id)
            
        except Exception as e:
            logger.error(f"Failed to update container {container_id}: {e}")
            raise DatabaseError(f"Container update failed: {e}")
    
    def delete(self, container_id: str) -> bool:
        """Delete container by ID"""
        try:
            with self.db.get_transaction() as conn:
                cursor = conn.execute(
                    "DELETE FROM Container WHERE id = ?",
                    (container_id,)
                )
                
                if cursor.rowcount > 0:
                    logger.info(f"Container deleted: {container_id}")
                    return True
                return False
                
        except Exception as e:
            logger.error(f"Failed to delete container {container_id}: {e}")
            raise DatabaseError(f"Container deletion failed: {e}")
    
    def get_all(self, limit: Optional[int] = None) -> List[Container]:
        """Get all containers with optional limit"""
        try:
            query = "SELECT * FROM Container ORDER BY updatedAt DESC"
            if limit:
                query += f" LIMIT {limit}"
            
            rows = self.db.fetchall(query)
            
            containers = []
            for row in rows:
                containers.append(Container(
                    id=row["id"],
                    qrCode=row["qrCode"],
                    isReturnable=bool(row["isReturnable"]),
                    dueDate=datetime.fromisoformat(row["dueDate"]) if row["dueDate"] else None,
                    updatedAt=datetime.fromisoformat(row["updatedAt"])
                ))
            
            return containers
            
        except Exception as e:
            logger.error(f"Failed to get all containers: {e}")
            raise DatabaseError(f"Container retrieval failed: {e}")
    
    def get_since(self, since: datetime, limit: Optional[int] = None) -> List[Container]:
        """Get containers updated since given datetime"""
        try:
            query = "SELECT * FROM Container WHERE updatedAt > ? ORDER BY updatedAt DESC"
            params = [since.isoformat()]
            
            if limit:
                query += f" LIMIT {limit}"
            
            rows = self.db.fetchall(query, params)
            
            containers = []
            for row in rows:
                containers.append(Container(
                    id=row["id"],
                    qrCode=row["qrCode"],
                    isReturnable=bool(row["isReturnable"]),
                    dueDate=datetime.fromisoformat(row["dueDate"]) if row["dueDate"] else None,
                    updatedAt=datetime.fromisoformat(row["updatedAt"])
                ))
            
            return containers
            
        except Exception as e:
            logger.error(f"Failed to get containers since {since}: {e}")
            raise DatabaseError(f"Container retrieval failed: {e}")
    
    def delete_all(self) -> bool:
        """Delete all containers"""
        try:
            with self.db.get_transaction() as conn:
                cursor = conn.execute("DELETE FROM Container")
                logger.info(f"Deleted {cursor.rowcount} containers")
                return True
                
        except Exception as e:
            logger.error(f"Failed to delete all containers: {e}")
            raise DatabaseError(f"Container bulk deletion failed: {e}")
    
    def create_with_id(self, container_id: str, container_data: ContainerCreate) -> Container:
        """Create a new container with specific ID"""
        try:
            now = datetime.utcnow().isoformat()
            
            with self.db.get_transaction() as conn:
                conn.execute("""
                    INSERT INTO Container (id, qrCode, isReturnable, dueDate, updatedAt)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    container_id,
                    container_data.qr_code,
                    1 if container_data.is_returnable else 0,
                    container_data.due_date.isoformat() if container_data.due_date else None,
                    now
                ))
            
            logger.debug(f"Container created with ID: {container_id}")
            return self.get_by_id(container_id) # type: ignore
            
        except Exception as e:
            logger.error(f"Failed to create container with ID {container_id}: {e}")
            raise DatabaseError(f"Container creation failed: {e}")


class DeviceStatusCRUD:
    """CRUD operations for DeviceStatus table"""
    
    def __init__(self, db: DatabaseConnection):
        self.db = db
    
    def get_status(self) -> Optional[DeviceStatus]:
        """Get current device status"""
        try:
            row = self.db.fetchone("SELECT * FROM DeviceStatus WHERE id = 1")
            
            if row:
                return DeviceStatus(
                    id=row["id"],
                    lastSyncAt=datetime.fromisoformat(row["lastSyncAt"]),
                    lastSeenAt=datetime.fromisoformat(row["lastSeenAt"]),
                    version=row["version"],
                    updateFailures=row["updateFailures"],
                    active=bool(row["active"]),
                    isInSafeMode=bool(row["isInSafeMode"])
                )
            return None
            
        except Exception as e:
            logger.error(f"Failed to get device status: {e}")
            raise DatabaseError(f"Device status retrieval failed: {e}")
    
    def update_status(self, updates: DeviceStatusUpdate) -> Optional[DeviceStatus]:
        """Update device status with given fields"""
        try:
            set_clauses = []
            params = {}
            
            if updates.last_sync_at:
                set_clauses.append("lastSyncAt = :lastSyncAt")
                params["lastSyncAt"] = updates.last_sync_at.isoformat()
            
            if updates.last_seen_at:
                set_clauses.append("lastSeenAt = :lastSeenAt")
                params["lastSeenAt"] = updates.last_seen_at.isoformat()
            
            if updates.version:
                set_clauses.append("version = :version")
                params["version"] = updates.version
            
            if updates.update_failures is not None:
                set_clauses.append("updateFailures = :updateFailures")
                params["updateFailures"] = updates.update_failures
            
            if updates.active is not None:
                set_clauses.append("active = :active")
                params["active"] = 1 if updates.active else 0
            
            if updates.is_in_safe_mode is not None:
                set_clauses.append("isInSafeMode = :isInSafeMode")
                params["isInSafeMode"] = 1 if updates.is_in_safe_mode else 0
            
            if not set_clauses:
                return self.get_status()
            
            query = f"UPDATE DeviceStatus SET {', '.join(set_clauses)} WHERE id = 1"
            
            with self.db.get_transaction() as conn:
                conn.execute(query, params)
            
            logger.info("Device status updated")
            return self.get_status()
            
        except Exception as e:
            logger.error(f"Failed to update device status: {e}")
            raise DatabaseError(f"Device status update failed: {e}")
    
    def update_sync_time(self) -> Optional[DeviceStatus]:
        """Update last sync time to current time"""
        now = datetime.utcnow()
        return self.update_status(DeviceStatusUpdate(last_sync_at=now))
    
    def update_seen_time(self) -> Optional[DeviceStatus]:
        """Update last seen time to current time"""
        now = datetime.utcnow()
        return self.update_status(DeviceStatusUpdate(last_seen_at=now))


class AuditLogCRUD:
    """CRUD operations for AuditLog table"""
    
    def __init__(self, db: DatabaseConnection):
        self.db = db
    
    def create_log(self, log_data: AuditLogCreate) -> AuditLog:
        """Create a new audit log entry"""
        try:
            log_id = str(uuid4())
            now = datetime.utcnow().isoformat()
            
            with self.db.get_transaction() as conn:
                conn.execute("""
                    INSERT INTO AuditLog (id, type, description, isOfflineAction, containerId, createdAt)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    log_id,
                    log_data.type.value,
                    log_data.description,
                    log_data.is_offline_action,
                    log_data.container_id,
                    now
                ))
            
            logger.debug(f"Audit log created: {log_id} - {log_data.type.value}")
            return self.get_by_id(log_id) # type: ignore
            
        except Exception as e:
            logger.error(f"Failed to create audit log: {e}")
            raise DatabaseError(f"Audit log creation failed: {e}")
    
    def get_by_id(self, log_id: str) -> Optional[AuditLog]:
        """Get audit log by ID"""
        try:
            row = self.db.fetchone(
                "SELECT * FROM AuditLog WHERE id = ?",
                (log_id,)
            )
            
            if row:
                return AuditLog(
                    id=row["id"],
                    type=LogType(row["type"]),
                    description=row["description"],
                    isOfflineAction=bool(row["isOfflineAction"]),
                    containerId=row["containerId"],
                    createdAt=datetime.fromisoformat(row["createdAt"])
                )
            return None
            
        except Exception as e:
            logger.error(f"Failed to get audit log by ID {log_id}: {e}")
            raise DatabaseError(f"Audit log retrieval failed: {e}")
    
    def get_logs_since(self, since: datetime, limit: Optional[int] = None) -> List[AuditLog]:
        """Get audit logs since given datetime"""
        try:
            if limit:
                query = """
                    SELECT * FROM AuditLog 
                    WHERE createdAt >= ? 
                    ORDER BY createdAt DESC
                    LIMIT ?
                """
                rows = self.db.fetchall(query, (since.isoformat(), limit))
            else:
                query = """
                    SELECT * FROM AuditLog 
                    WHERE createdAt >= ? 
                    ORDER BY createdAt DESC
                """
                rows = self.db.fetchall(query, (since.isoformat(),))
            
            logs = []
            for row in rows:
                logs.append(AuditLog(
                    id=row["id"],
                    type=LogType(row["type"]),
                    description=row["description"],
                    isOfflineAction=bool(row["isOfflineAction"]),
                    containerId=row["containerId"],
                    createdAt=datetime.fromisoformat(row["createdAt"])
                ))
            
            return logs
            
        except Exception as e:
            logger.error(f"Failed to get audit logs since {since}: {e}")
            raise DatabaseError(f"Audit log retrieval failed: {e}")
    
    def get_logs_by_type(self, log_type: LogType, limit: Optional[int] = None) -> List[AuditLog]:
        """Get audit logs by type"""
        try:
            if limit:
                query = """
                    SELECT * FROM AuditLog 
                    WHERE type = ? 
                    ORDER BY createdAt DESC
                    LIMIT ?
                """
                rows = self.db.fetchall(query, (log_type.value, limit))
            else:
                query = """
                    SELECT * FROM AuditLog 
                    WHERE type = ? 
                    ORDER BY createdAt DESC
                """
                rows = self.db.fetchall(query, (log_type.value,))
            
            logs = []
            for row in rows:
                logs.append(AuditLog(
                    id=row["id"],
                    type=LogType(row["type"]),
                    description=row["description"],
                    isOfflineAction=bool(row["isOfflineAction"]),
                    containerId=row["containerId"],
                    createdAt=datetime.fromisoformat(row["createdAt"])
                ))
            
            return logs
            
        except Exception as e:
            logger.error(f"Failed to get audit logs by type {log_type}: {e}")
            raise DatabaseError(f"Audit log retrieval failed: {e}")
    
    def delete_logs_before(self, before: datetime) -> int:
        """Delete audit logs before given datetime"""
        try:
            with self.db.get_transaction() as conn:
                cursor = conn.execute(
                    "DELETE FROM AuditLog WHERE createdAt < ?",
                    (before.isoformat(),)
                )
                
                deleted_count = cursor.rowcount
                logger.info(f"Deleted {deleted_count} audit logs before {before}")
                return deleted_count
                
        except Exception as e:
            logger.error(f"Failed to delete audit logs before {before}: {e}")
            raise DatabaseError(f"Audit log deletion failed: {e}")
    
    def delete_log(self, log_id: str) -> bool:
        """Delete audit log by ID"""
        try:
            with self.db.get_transaction() as conn:
                cursor = conn.execute(
                    "DELETE FROM AuditLog WHERE id = ?",
                    (log_id,)
                )
                
                if cursor.rowcount > 0:
                    logger.debug(f"Audit log deleted: {log_id}")
                    return True
                else:
                    logger.warning(f"Audit log not found for deletion: {log_id}")
                    return False
                    
        except Exception as e:
            logger.error(f"Failed to delete audit log {log_id}: {e}")
            raise DatabaseError(f"Audit log deletion failed: {e}")
    
    def delete_all(self) -> bool:
        """Delete all audit logs"""
        try:
            with self.db.get_transaction() as conn:
                cursor = conn.execute("DELETE FROM AuditLog")
                logger.info(f"Deleted {cursor.rowcount} audit logs")
                return True
                
        except Exception as e:
            logger.error(f"Failed to delete all audit logs: {e}")
            raise DatabaseError(f"Audit log bulk deletion failed: {e}")


class DatabaseManager:
    """Main database manager combining all CRUD operations"""
    
    def __init__(self, db: DatabaseConnection):
        self.db = db
        self.containers = ContainerCRUD(db)
        self.device_status = DeviceStatusCRUD(db)
        self.audit_logs = AuditLogCRUD(db)
    
    def initialize(self):
        """Initialize database and all tables"""
        self.db.initialize_database()
    
    def close(self):
        """Close database connection"""
        self.db.close() 