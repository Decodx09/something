"""
Database connection management for the Container Return System
"""

import sqlite3
import logging
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional, Generator, Any, Dict, List
from threading import Lock

logger = logging.getLogger(__name__)


class DatabaseError(Exception):
    """Custom exception for database operations"""
    pass


class DatabaseConnection:
    """SQLite database connection manager with proper error handling"""
    
    def __init__(self, database_url: str):
        self.database_url = database_url
        self._lock = Lock()
        self._connection: Optional[sqlite3.Connection] = None
        self._is_initialized = False
        
    def _get_db_path(self) -> str:
        """Extract database path from URL"""
        if self.database_url.startswith("sqlite:///"):
            return self.database_url[10:]  # Remove "sqlite:///"
        return self.database_url
    
    def _create_connection(self) -> sqlite3.Connection:
        """Create a new database connection with proper settings"""
        try:
            db_path = self._get_db_path()
            
            # Ensure directory exists
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            
            # Create connection with WAL mode for better concurrency
            conn = sqlite3.connect(
                db_path,
                check_same_thread=False,
                timeout=30.0,  # 30 second timeout
                isolation_level=None  # Enable autocommit mode
            )
            
            # Enable WAL mode for better concurrency
            conn.execute("PRAGMA journal_mode=WAL")
            
            # Enable foreign key constraints
            conn.execute("PRAGMA foreign_keys=ON")
            
            # Set row factory for dict-like access
            conn.row_factory = sqlite3.Row
            
            logger.info(f"Database connection established: {db_path}")
            return conn
            
        except sqlite3.Error as e:
            logger.error(f"Failed to create database connection: {e}")
            raise DatabaseError(f"Database connection failed: {e}")
    
    def get_connection(self) -> sqlite3.Connection:
        """Get or create database connection"""
        with self._lock:
            if self._connection is None:
                self._connection = self._create_connection()
            return self._connection
    
    @contextmanager
    def get_transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for database transactions"""
        conn = self.get_connection()
        try:
            conn.execute("BEGIN TRANSACTION")
            yield conn
            conn.execute("COMMIT")
        except Exception as e:
            conn.execute("ROLLBACK")
            logger.error(f"Transaction rolled back: {e}")
            raise DatabaseError(f"Transaction failed: {e}")
    
    def execute_query(self, query: str, params: Optional[Any] = None) -> sqlite3.Cursor:
        """Execute a query with optional parameters"""
        conn = self.get_connection()
        try:
            if params:
                return conn.execute(query, params)
            return conn.execute(query)
        except sqlite3.Error as e:
            logger.error(f"Query execution failed: {query[:100]}... Error: {e}")
            raise DatabaseError(f"Query execution failed: {e}")
    
    def execute_many(self, query: str, params_list: List[Any]) -> sqlite3.Cursor:
        """Execute query with multiple parameter sets"""
        conn = self.get_connection()
        try:
            return conn.executemany(query, params_list)
        except sqlite3.Error as e:
            logger.error(f"Batch query execution failed: {query[:100]}... Error: {e}")
            raise DatabaseError(f"Batch query execution failed: {e}")
    
    def fetchone(self, query: str, params: Optional[Any] = None) -> Optional[sqlite3.Row]:
        """Execute query and fetch one result"""
        cursor = self.execute_query(query, params)
        return cursor.fetchone()
    
    def fetchall(self, query: str, params: Optional[Any] = None) -> List[sqlite3.Row]:
        """Execute query and fetch all results"""
        cursor = self.execute_query(query, params)
        return cursor.fetchall()
    
    def initialize_database(self) -> None:
        """Initialize database with required tables"""
        if self._is_initialized:
            return
            
        try:
            with self.get_transaction() as conn:
                # Create Container table
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS Container (
                        id TEXT PRIMARY KEY,
                        qrCode TEXT UNIQUE NOT NULL,
                        isReturnable BOOLEAN NOT NULL,
                        dueDate DATETIME,
                        updatedAt DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Create DeviceStatus table
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS DeviceStatus (
                        id INTEGER PRIMARY KEY DEFAULT 1,
                        lastSyncAt DATETIME NOT NULL,
                        lastSeenAt DATETIME NOT NULL,
                        version TEXT NOT NULL,
                        updateFailures INTEGER DEFAULT 0,
                        active BOOLEAN DEFAULT TRUE,
                        isInSafeMode BOOLEAN DEFAULT FALSE,
                        CHECK (id = 1)
                    )
                """)
                
                # Create AuditLog table
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS AuditLog (
                        id TEXT PRIMARY KEY,
                        type TEXT NOT NULL CHECK (type IN ('ERROR', 'INFO', 'RETURN_VALID', 'RETURN_INVALID')),
                        description TEXT NOT NULL,
                        isOfflineAction BOOLEAN NOT NULL,
                        containerId TEXT,
                        createdAt DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (containerId) REFERENCES Container(id)
                    )
                """)
                
                # Create indexes for performance
                conn.execute("CREATE INDEX IF NOT EXISTS idx_container_qrcode ON Container(qrCode)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_container_updated ON Container(updatedAt)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_auditlog_created ON AuditLog(createdAt)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_auditlog_type ON AuditLog(type)")
                
                # Initialize DeviceStatus if not exists
                existing_status = conn.execute("SELECT COUNT(*) FROM DeviceStatus").fetchone()
                if existing_status[0] == 0:
                    now = datetime.utcnow().isoformat()
                    conn.execute("""
                        INSERT INTO DeviceStatus (lastSyncAt, lastSeenAt, version)
                        VALUES (?, ?, ?)
                    """, (now, now, "1.0.0"))
                
                logger.info("Database initialized successfully")
                self._is_initialized = True
                
        except sqlite3.Error as e:
            logger.error(f"Database initialization failed: {e}")
            raise DatabaseError(f"Database initialization failed: {e}")
    
    def close(self) -> None:
        """Close database connection"""
        with self._lock:
            if self._connection:
                self._connection.close()
                self._connection = None
                logger.info("Database connection closed")
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# Global database instance
_db_instance: Optional[DatabaseConnection] = None


def get_database(database_url: str) -> DatabaseConnection:
    """Get or create database instance"""
    global _db_instance
    if _db_instance is None:
        _db_instance = DatabaseConnection(database_url)
    return _db_instance


def close_database() -> None:
    """Close global database instance"""
    global _db_instance
    if _db_instance:
        _db_instance.close()
        _db_instance = None 