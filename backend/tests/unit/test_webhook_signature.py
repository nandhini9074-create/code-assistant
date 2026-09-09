"""
tests/unit/test_webhook_signature.py
Tests for GitHub webhook payload signature verification.
"""

import hmac
import hashlib
import pytest
from unittest.mock import patch

from app.core.exceptions import WebhookVerificationError, ConfigurationError
from app.infrastructure.github.webhook_verifier import verify_webhook_payload


def _generate_signature(secret: str, payload: bytes) -> str:
    """Generate a valid HMAC-SHA256 signature for testing."""
    mac = hmac.new(secret.encode("utf-8"), msg=payload, digestmod=hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


@pytest.fixture
def mock_settings():
    with patch("app.infrastructure.github.webhook_verifier.get_settings") as mock_get_settings:
        settings = mock_get_settings.return_value
        settings.github_webhook_secret = "test-secret"
        yield settings


def test_verify_webhook_payload_valid(mock_settings):
    """Test that a valid signature passes verification."""
    payload = b'{"hello": "world"}'
    signature = _generate_signature("test-secret", payload)
    
    # Should not raise any exception
    verify_webhook_payload(payload, signature)


def test_verify_webhook_payload_invalid(mock_settings):
    """Test that an invalid signature raises WebhookVerificationError."""
    payload = b'{"hello": "world"}'
    signature = _generate_signature("wrong-secret", payload)
    
    with pytest.raises(WebhookVerificationError):
        verify_webhook_payload(payload, signature)


def test_verify_webhook_payload_missing_secret(mock_settings):
    """Test that missing configuration raises ConfigurationError."""
    mock_settings.github_webhook_secret = None
    payload = b'{"hello": "world"}'
    signature = "sha256=dummy"
    
    with pytest.raises(ConfigurationError):
        verify_webhook_payload(payload, signature)


def test_verify_webhook_payload_malformed_signature(mock_settings):
    """Test that malformed signature header raises WebhookVerificationError."""
    payload = b'{"hello": "world"}'
    signature = "dummy-signature"
    
    with pytest.raises(WebhookVerificationError):
        verify_webhook_payload(payload, signature)
