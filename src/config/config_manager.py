"""
Simple configuration manager that loads settings from environment variables.
"""

import os
from typing import Any, Dict, Optional
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
env_path = Path('.env')
if env_path.exists():
    load_dotenv(env_path)


class ConfigManager:
    """Simple configuration manager for environment variables."""
    
    def __init__(self) -> None:
        self._config: Dict[str, Any] = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from environment variables."""
        return {
            # Device Identity
            'raspberry_name': os.getenv('RASPBERRY_NAME', 'device_001'),
            'device_name': os.getenv('DEVICE_NAME', 'device_001'),  # Keep for backward compatibility
            
            # API Configuration
            'base_api_url': os.getenv('BASE_API_URL', ''),
            'api_key': "Bearer " + os.getenv('API_KEY', ''),
            'raspberry_api_key': os.getenv('RASPBERRY_API_KEY', ''),
            'healthcheck_interval': int(os.getenv('HEALTHCHECK_INTERVAL', '180')),
            'sync_interval': int(os.getenv('SYNC_INTERVAL', '600')),
            'api_timeout': int(os.getenv('API_TIMEOUT', '30')),
            'api_retry_attempts': int(os.getenv('API_RETRY_ATTEMPTS', '3')),
            
            # Database
            'database_url': os.getenv('DATABASE_URL', 'sqlite:///container_system.db'),
            
            # UART
            'uart_port': os.getenv('UART_PORT', '/dev/ttyUSB0'),
            'uart_baudrate': int(os.getenv('UART_BAUDRATE', '9600')),
            
            # Logging
            'log_level': os.getenv('LOG_LEVEL', 'INFO').upper(),
            'log_file': os.getenv('LOG_FILE', 'logs/system.log'),
            'debug': os.getenv('DEBUG', 'false').lower() == 'true',
            
            # Application
            'app_version': os.getenv('APP_VERSION', '1.0.0'),
            
            # QR Scanner
            'qr_scanner_device': os.getenv('QR_SCANNER_DEVICE', '/dev/hidraw2'),
        }
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value."""
        return self._config.get(key, default)
    
    def get_all(self) -> Dict[str, Any]:
        """Get all configuration values."""
        return self._config.copy()
    
    @property
    def raspberry_name(self) -> str:
        return self.get('raspberry_name')
    
    @property
    def device_name(self) -> str:
        return self.get('device_name')
    
    @property
    def base_api_url(self) -> str:
        return self.get('base_api_url')
    
    @property
    def api_key(self) -> str:
        return self.get('api_key')
    
    @property
    def raspberry_api_key(self) -> str:
        return self.get('raspberry_api_key')
    
    @property
    def healthcheck_interval(self) -> int:
        return self.get('healthcheck_interval')
    
    @property
    def sync_interval(self) -> int:
        return self.get('sync_interval')
    
    @property
    def api_timeout(self) -> int:
        return self.get('api_timeout')
    
    @property
    def api_retry_attempts(self) -> int:
        return self.get('api_retry_attempts')
    
    @property
    def database_url(self) -> str:
        return self.get('database_url')
    
    @property
    def uart_port(self) -> str:
        return self.get('uart_port')
    
    @property
    def uart_baudrate(self) -> int:
        return self.get('uart_baudrate')
    
    @property
    def log_level(self) -> str:
        return self.get('log_level')
    
    @property
    def log_file(self) -> str:
        return self.get('log_file')
    
    @property
    def debug(self) -> bool:
        return self.get('debug')
    
    @property
    def app_version(self) -> str:
        return self.get('app_version')
    
    @property
    def qr_scanner_device(self) -> str:
        return self.get('qr_scanner_device')


# Global config instance
_config: Optional[ConfigManager] = None


def get_config() -> ConfigManager:
    """Get global configuration manager."""
    global _config
    if _config is None:
        _config = ConfigManager()
    return _config 