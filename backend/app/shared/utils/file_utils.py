"""
app/shared/utils/file_utils.py
Utilities for file extension mapping and binary detection.
"""

from pathlib import Path

# Mapping of file extensions to their canonical language name
EXTENSION_TO_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".swift": "swift",
    ".md": "markdown",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".html": "html",
    ".css": "css",
}


def get_language_from_extension(file_path: str) -> str | None:
    """Determine the programming language from the file extension."""
    ext = Path(file_path).suffix.lower()
    return EXTENSION_TO_LANGUAGE.get(ext)


def is_binary_content(content: bytes) -> bool:
    """
    Heuristic to determine if byte content is binary.
    Checks for the presence of null bytes in the first chunk.
    """
    return b"\x00" in content[:8192]
