"""
Simple QR processor for container return system.

Processes QR codes scanned from USB scanner and validates them.
"""

import time
import logging
import uuid
import hmac
import hashlib
import base64
import re
import os
from typing import Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ValidationResult(Enum):
    """QR code validation results."""
    VALID = "valid"
    INVALID_FORMAT = "invalid_format"
    INVALID_LENGTH = "invalid_length"
    INVALID_CHARACTERS = "invalid_characters"
    INVALID_URL_FORMAT = "invalid_url_format"
    INVALID_HASH = "invalid_hash"
    FRAUD_ATTEMPT = "fraud_attempt"


@dataclass
class QRProcessingResult:
    """Result of QR code processing."""
    qr_code: str
    validation: ValidationResult
    container_id: Optional[str] = None
    processing_time: float = 0.0
    error_message: Optional[str] = None
    is_fraud_attempt: bool = False
    parsed_url: Optional[Dict[str, str]] = None


class QRProcessor:
    """
    QR processor for container validation with URL-based QR codes.
    
    Validates QR codes in URL format: http://paka.eco/QR/[CODE]/[HASH]
    Verifies HMAC hash to prevent fraud attempts.
    """
    
    def __init__(self, db_manager=None):
        """Initialize the QR processor."""
        self.min_qr_length = 6
        self.max_qr_length = 200  # Increased for URL format
        self.db_manager = db_manager
        
        # QR validation configuration
        self.private_key = os.getenv('PRIVATE_KEY_QR', 'default_key')
        self.url_pattern = re.compile(
            r'.*https?:\/\/paka\.eco\/QR\/([A-HJ-NP-Z2-9]{6})\/([A-Z0-9]{6})$',
            re.IGNORECASE
        )
        self.hash_length = 6
        
        logger.info("QR processor initialized with URL validation")
    
    def process_qr_code(self, qr_code: str) -> QRProcessingResult:
        """
        Process a scanned QR code with URL validation and hash verification.
        
        Args:
            qr_code: The scanned QR code string (expected URL format)
            
        Returns:
            Processing result with validation status and fraud detection
        """
        start_time = time.time()
        
        try:
            qr_code = qr_code.strip()
            
            # Step 1: Parse and validate URL format
            parsed_url = self._parse_scanned_url(qr_code)
            
            result = QRProcessingResult(
                qr_code=qr_code,
                validation=ValidationResult.INVALID_FORMAT,
                processing_time=0.0,
                parsed_url=parsed_url
            )
            
            if not parsed_url:
                # Invalid URL format - treat as fraud attempt
                result.validation = ValidationResult.FRAUD_ATTEMPT
                result.is_fraud_attempt = True
                result.error_message = "Invalid URL format. Expected: http://paka.eco/QR/[CODE]/[HASH]"
                logger.warning(f"Fraud attempt detected - invalid URL format: {qr_code}")
                result.processing_time = time.time() - start_time
                return result
            
            # Step 2: Validate HMAC hash
            code = parsed_url['code']
            provided_hash = parsed_url['hash']
            expected_hash = self._generate_hmac_hash(code)
            
            if provided_hash != expected_hash:
                # Invalid hash - treat as fraud attempt
                result.validation = ValidationResult.FRAUD_ATTEMPT
                result.is_fraud_attempt = True
                result.error_message = "Invalid hash. The QR code may be corrupted or fraudulent"
                logger.warning(f"Fraud attempt detected - invalid hash: {qr_code} (expected: {expected_hash}, got: {provided_hash})")
                result.processing_time = time.time() - start_time
                return result
            
            # Step 3: Valid QR code - proceed as before
            result.validation = ValidationResult.VALID
            result.container_id = code
            
            logger.info(f"QR code validated successfully: {qr_code} -> {code}")
            result.processing_time = time.time() - start_time
            return result
            
        except Exception as e:
            logger.error(f"Error processing QR code '{qr_code}': {e}", exc_info=True)
            return QRProcessingResult(
                qr_code=qr_code,
                validation=ValidationResult.INVALID_FORMAT,
                processing_time=time.time() - start_time,
                error_message=f"Processing error: {str(e)}"
            )
    
    def _parse_scanned_url(self, url: str) -> Optional[Dict[str, str]]:
        """
        Parse and validate the scanned URL format.
        
        Expected format: http://paka.eco/QR/[CODE]/[HASH]
        CODE: 6-character alphanumeric code (Base32 without I, L, O, U)
        HASH: 6-character hash for validation
        
        Args:
            url: Scanned URL string
            
        Returns:
            Dictionary with 'code' and 'hash' keys if valid, None otherwise
        """
        if not url or not isinstance(url, str):
            return None
        
        match = self.url_pattern.match(url.strip())
        if not match:
            return None
        
        return {
            'code': match.group(1).upper(),
            'hash': match.group(2).upper()
        }
    
    def _generate_hmac_hash(self, code: str) -> str:
        """
        Generate HMAC hash for the given code using SHA256 and Base32 encoding.

        Args:
            code: The container code to generate hash for

        Returns:
            6-character Base32 encoded hash
        """
        # Create HMAC with SHA256
        hmac_obj = hmac.new(
            self.private_key.encode('utf-8'),
            code.encode('utf-8'),
            hashlib.sha256
        )

        # Get raw digest
        raw_digest = hmac_obj.digest()

        # Encode with Base32 using standard library (matches JavaScript base32.js)
        encoded = base64.b32encode(raw_digest).decode('utf-8')

        # Return first 6 characters
        return encoded[:self.hash_length].upper()
    
    def is_fraud_attempt(self, result: QRProcessingResult) -> bool:
        """
        Check if the QR processing result indicates a fraud attempt.
        
        Args:
            result: QR processing result
            
        Returns:
            True if fraud attempt detected
        """
        return result.is_fraud_attempt or result.validation == ValidationResult.FRAUD_ATTEMPT
    
    def get_status(self) -> Dict[str, Any]:
        """Get processor status."""
        return {
            "min_qr_length": self.min_qr_length,
            "max_qr_length": self.max_qr_length,
            "hash_length": self.hash_length,
            "url_pattern": self.url_pattern.pattern,
            "private_key_configured": bool(self.private_key and self.private_key != 'default_key')
        }