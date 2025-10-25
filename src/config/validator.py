"""
Simple configuration validator for environment variables.
"""

import os
from pathlib import Path
from typing import  Dict, Any


class ConfigValidator:
    """Validates configuration values."""
    
    @staticmethod
    def validate() -> Dict[str, Any]:
        """
        Validate configuration and return errors/warnings.
        
        Returns:
            Dict with 'errors' and 'warnings' lists, and 'valid' boolean
        """
        errors = []
        warnings = []
        
        # Validate API keys (required for production)
        api_key = os.getenv('API_KEY', '')
        raspberry_api_key = os.getenv('RASPBERRY_API_KEY', '')
        
        if not api_key:
            errors.append("API_KEY not set - required for API authentication")
        
        if not raspberry_api_key:
            errors.append("RASPBERRY_API_KEY not set - required for device authentication")
        
        # Validate raspberry name
        raspberry_name = os.getenv('RASPBERRY_NAME', 'device_001')
        if raspberry_name == 'device_001':
            errors.append("RASPBERRY_NAME using default value - consider setting unique device name")
        
        # Validate log level
        log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if log_level not in valid_levels:
            errors.append(f"Invalid LOG_LEVEL '{log_level}'. Must be one of: {', '.join(valid_levels)}")
        
        # Validate UART baudrate
        try:
            baudrate = int(os.getenv('UART_BAUDRATE', '9600'))
            valid_rates = [9600, 19200, 38400, 57600, 115200]
            if baudrate not in valid_rates:
                errors.append(f"Invalid UART_BAUDRATE '{baudrate}'. Must be one of: {', '.join(map(str, valid_rates))}")
        except ValueError:
            errors.append("UART_BAUDRATE must be a valid integer")
        
        # Check if log directory can be created
        log_file = os.getenv('LOG_FILE', 'logs/system.log')
        log_path = Path(log_file)
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            errors.append(f"Cannot create log directory: {e}")
        
        # Check database directory
        database_url = os.getenv('DATABASE_URL', 'sqlite:///container_system.db')
        if database_url.startswith('sqlite:///'):
            db_path = Path(database_url[10:])  # Remove 'sqlite:///'
            try:
                db_path.parent.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                errors.append(f"Cannot create database directory: {e}")
        
        # Check UART port (warning only)
        uart_port = os.getenv('UART_PORT', '/dev/ttyUSB0')
        debug = os.getenv('DEBUG', 'false').lower() == 'true'
        if not debug and not Path(uart_port).exists():
            warnings.append(f"UART port not accessible: {uart_port}")
        
        return {
            'errors': errors,
            'warnings': warnings,
            'valid': len(errors) == 0
        }


def validate_config() -> bool:
    """Validate configuration and print results."""
    result = ConfigValidator.validate()
    
    if result['errors']:
        print("Configuration errors:")
        for error in result['errors']:
            print(f"  ERROR: {error}")
    
    if result['warnings']:
        print("Configuration warnings:")
        for warning in result['warnings']:
            print(f"  WARNING: {warning}")
    
    return bool(result['valid']) 