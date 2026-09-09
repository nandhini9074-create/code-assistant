"""
tests/unit/ingestion/test_zip_storage.py
Unit tests for ZipStorageManager.
"""

import io
import os
import zipfile
import pytest

from app.core.exceptions import ZipSecurityError
from app.infrastructure.storage.zip_storage import ZipStorageManager


def create_mock_zip(files: dict[str, str]) -> io.BytesIO:
    """Helper to create an in-memory zip file."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, content in files.items():
            zf.writestr(filename, content)
    buffer.seek(0)
    return buffer


def test_calculate_zip_hash() -> None:
    zip_bytes = create_mock_zip({"test.py": "print('hello world')"})
    hash1 = ZipStorageManager.calculate_zip_hash(zip_bytes)
    assert len(hash1) == 64  # SHA-256 hex string

    # Ensure stream position was reset and calculation is deterministic
    hash2 = ZipStorageManager.calculate_zip_hash(zip_bytes)
    assert hash1 == hash2


def test_extract_securely_success() -> None:
    zip_bytes = create_mock_zip({"main.py": "def main(): pass", "readme.md": "# Readme"})
    extracted_dir = ZipStorageManager.extract_securely(zip_bytes)
    
    try:
        assert os.path.exists(extracted_dir)
        assert os.path.exists(os.path.join(extracted_dir, "main.py"))
        assert os.path.exists(os.path.join(extracted_dir, "readme.md"))
    finally:
        ZipStorageManager.cleanup(extracted_dir)
        assert not os.path.exists(extracted_dir)


def test_path_traversal_detection() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("../malicious.py", "import os; os.system('echo hacked')")
    buffer.seek(0)

    with pytest.raises(ZipSecurityError, match="Path traversal detected"):
        ZipStorageManager.extract_securely(buffer)
