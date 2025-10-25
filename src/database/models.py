"""
Database models for the Container Return System
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class LogType(str, Enum):
    """Enum for audit log types"""
    ERROR = "ERROR"
    INFO = "INFO"
    RETURN_VALID = "RETURN_VALID"
    RETURN_INVALID = "RETURN_INVALID"


class Container(BaseModel):
    """Container model for database operations"""
    id: str = Field(default_factory=lambda: str(uuid4()))
    qr_code: str = Field(..., alias="qrCode")
    is_returnable: bool = Field(..., alias="isReturnable")
    due_date: Optional[datetime] = Field(None, alias="dueDate")
    updated_at: datetime = Field(default_factory=datetime.utcnow, alias="updatedAt")

    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class DeviceStatus(BaseModel):
    """Device status model for database operations"""
    id: int = Field(default=1)
    last_sync_at: datetime = Field(..., alias="lastSyncAt")
    last_seen_at: datetime = Field(..., alias="lastSeenAt")
    version: str
    update_failures: int = Field(default=0, alias="updateFailures")
    active: bool = Field(default=True)
    is_in_safe_mode: bool = Field(default=False, alias="isInSafeMode")

    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class AuditLog(BaseModel):
    """Audit log model for database operations"""
    id: str = Field(default_factory=lambda: str(uuid4()))
    type: LogType
    description: str
    is_offline_action: bool = Field(..., alias="isOfflineAction")
    container_id: Optional[str] = Field(None, alias="containerId")
    created_at: datetime = Field(default_factory=datetime.utcnow, alias="createdAt")

    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


# Database creation models (for raw SQL operations)
class ContainerCreate(BaseModel):
    """Model for creating new containers"""
    qr_code: str
    is_returnable: bool
    due_date: Optional[datetime] = None


class DeviceStatusUpdate(BaseModel):
    """Model for updating device status"""
    last_sync_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    version: Optional[str] = None
    update_failures: Optional[int] = None
    active: Optional[bool] = None
    is_in_safe_mode: Optional[bool] = None


class AuditLogCreate(BaseModel):
    """Model for creating audit logs"""
    type: LogType
    description: str
    is_offline_action: bool
    container_id: Optional[str] = None 