"""
Simple API module for server communication
"""

from .client import APIClient
from .service import APIService

__all__ = ['APIClient', 'APIService']