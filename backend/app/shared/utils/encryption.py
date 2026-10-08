import base64
import hashlib
from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

def _get_fernet_key() -> bytes:
    """
    Derives a 32-byte url-safe base64-encoded key from the APP_SECRET_KEY.
    """
    settings = get_settings()
    secret = settings.app_secret_key.encode("utf-8")
    
    # Hash the secret to ensure it's exactly 32 bytes, then base64 encode it
    # to meet the Fernet key requirements.
    digest = hashlib.sha256(secret).digest()
    return base64.urlsafe_b64encode(digest)

def encrypt_token(token: str | None) -> str | None:
    """
    Encrypts a plaintext token using Fernet symmetric encryption.
    Returns None if the token is None or empty.
    """
    if not token:
        return token
        
    try:
        f = Fernet(_get_fernet_key())
        return f.encrypt(token.encode("utf-8")).decode("utf-8")
    except Exception as e:
        logger.error("token_encryption_failed", error=str(e))
        # Don't return the raw token on failure, raise so it isn't stored in plaintext
        raise ValueError(f"Failed to encrypt token: {e}")

def decrypt_token(encrypted_token: str | None) -> str | None:
    """
    Decrypts an encrypted token.
    If decryption fails, assumes the token is a plaintext legacy token and returns it as-is.
    Returns None if the token is None or empty.
    """
    if not encrypted_token:
        return encrypted_token
        
    f = Fernet(_get_fernet_key())
    
    try:
        return f.decrypt(encrypted_token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        # Backward compatibility for existing plaintext tokens in DB
        logger.debug("token_decryption_failed_assuming_plaintext")
        return encrypted_token
    except Exception as e:
        logger.error("token_decryption_unexpected_error", error=str(e))
        return encrypted_token
