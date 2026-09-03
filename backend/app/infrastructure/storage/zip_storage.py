"""
app/infrastructure/storage/zip_storage.py
Secure ZIP extraction.
"""

import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import IO

from app.core.exceptions import ZipSecurityError


class ZipStorageManager:
    """Manages secure ZIP extraction and cleanup."""
    
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
    MAX_TOTAL_SIZE = 500 * 1024 * 1024  # 500MB
    MAX_FILES = 10000

    @classmethod
    def extract_securely(cls, zip_file: IO[bytes]) -> str:
        """
        Securely extract a ZIP file to a temporary directory.
        Returns the path to the extracted directory.
        Caller is responsible for cleaning it up.
        """
        temp_dir = tempfile.mkdtemp(prefix="code_explorer_zip_")
        
        try:
            with zipfile.ZipFile(zip_file, "r") as zf:
                total_size = 0
                file_count = 0
                
                for zip_info in zf.infolist():
                    # Skip directories
                    if zip_info.is_dir():
                        continue
                        
                    # Zip bomb protection
                    file_count += 1
                    if file_count > cls.MAX_FILES:
                        raise ZipSecurityError(f"Too many files in ZIP (max {cls.MAX_FILES})")
                        
                    total_size += zip_info.file_size
                    if total_size > cls.MAX_TOTAL_SIZE:
                        raise ZipSecurityError(f"Total extracted size exceeds limit (max {cls.MAX_TOTAL_SIZE} bytes)")
                        
                    if zip_info.file_size > cls.MAX_FILE_SIZE:
                        # Skip oversized files rather than failing entire ingestion,
                        # or could throw an error. Skipping is usually better for codebases.
                        continue
                        
                    # Path traversal protection
                    target_path = os.path.abspath(os.path.join(temp_dir, zip_info.filename))
                    if not target_path.startswith(os.path.abspath(temp_dir)):
                        raise ZipSecurityError(f"Path traversal detected in ZIP: {zip_info.filename}")
                        
                    zf.extract(zip_info, temp_dir)
                    
            return temp_dir
            
        except Exception as exc:
            # Cleanup on failure
            cls.cleanup(temp_dir)
            raise ZipSecurityError(f"Failed to process ZIP securely: {str(exc)}") from exc

    @staticmethod
    def cleanup(temp_dir: str) -> None:
        """Remove a temporary extraction directory."""
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
