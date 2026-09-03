"""
app/shared/utils/hashing.py
Hashing utilities.
"""

import hashlib


def sha256_content(content: bytes) -> str:
    """Compute the SHA-256 hash of bytes content."""
    return hashlib.sha256(content).hexdigest()


def sha256_text(text: str) -> str:
    """Compute the SHA-256 hash of a string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
