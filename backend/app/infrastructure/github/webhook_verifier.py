"""
app/infrastructure/github/webhook_verifier.py
Verifies GitHub webhook payloads.
"""

from __future__ import annotations

from app.config import get_settings
from app.core.security import verify_github_signature


def verify_webhook_payload(payload_body: bytes, signature_header: str) -> None:
    """
    Verify a GitHub webhook payload signature against the configured secret.
    
    Args:
        payload_body: The raw request body bytes.
        signature_header: The value of the X-Hub-Signature-256 header.
        
    Raises:
        WebhookVerificationError: If the signature is invalid or missing.
        ConfigurationError: If the webhook secret is not configured.
    """
    settings = get_settings()
    secret = settings.github_webhook_secret
    
    if not secret:
        from app.core.exceptions import ConfigurationError
        raise ConfigurationError(
            "GITHUB_WEBHOOK_SECRET is not configured.", 
            code="MISSING_WEBHOOK_SECRET"
        )
        
    verify_github_signature(
        payload_body=payload_body,
        signature_header=signature_header,
        secret=secret,
    )
