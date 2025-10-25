"""
Simple API client for healthcheck and sync operations
"""

import logging
import requests
import json
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class APIClient:
    """Simple API client for server communication."""
    
    def __init__(self, config_manager):
        self.config = config_manager
        
        # Get configuration values
        self.base_url = self.config.base_api_url
        self.authorization = self.config.api_key  # Authorization header uses API_KEY
        self.api_key = self.config.raspberry_api_key
        self.device_name = self.config.raspberry_name
        
        # Validate required values
        if not self.base_url:
            raise ValueError("BASE_API_URL configuration is required")
        if not self.authorization:
            raise ValueError("API_KEY configuration is required")
        if not self.api_key:
            raise ValueError("RASPBERRY_API_KEY configuration is required")
        if not self.device_name:
            raise ValueError("RASPBERRY_NAME configuration is required")
        
        # Build headers
        self.headers = {
            'Content-Type': 'application/json',
            'Authorization': self.authorization,
            'x-api-key': self.api_key,
            'x-name': self.device_name
        }
        
        # Request timeout
        self.timeout = self.config.get('api.timeout', 30)
        
        logger.info(f"API client initialized for device: {self.device_name}")
    
    def _make_request(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Make API request."""
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = requests.post(
                url,
                headers=self.headers,
                data=json.dumps(data),
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.Timeout:
            logger.error(f"API request timeout: {endpoint}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {endpoint} - {e}")
            raise
    
    def healthcheck(self, version: str, update_failures: int) -> Dict[str, Any]:
        """Send healthcheck to server."""
        data = {
            "version": version,
            "updateFailures": update_failures
        }
        return self._make_request('/functions/v1/raspberry-healthcheck', data)
    
    def sync(self, logs: List[Dict], containers: List[Dict]) -> Dict[str, Any]:
        """Send sync data to server."""
        data = {
            "logs": logs,
            "containers": containers
        }
        logger.debug(f"Sync request data structure: logs={len(logs)}, containers={len(containers)}")
        return self._make_request('/functions/v1/raspberry-sync', data)
    
    def validate_container(self, container_id: str) -> Dict[str, Any]:
        """Validate container with server."""
        data = {
            "id": container_id
        }
        return self._make_request('/functions/v1/raspberry-container-validate', data)