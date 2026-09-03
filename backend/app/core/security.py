"""
app/core/security.py
Security helpers for Code Explorer.

Covers:
  - GitHub webhook HMAC-SHA256 verification (constant-time)
  - ZIP path traversal and bomb protection helpers
  - Input sanitization utilities
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from pathlib import PurePosixPath

from app.core.constants import (
    GITHUB_SIGNATURE_PREFIX,
    MAX_ZIP_FILE_COUNT,
    MAX_ZIP_SINGLE_FILE_BYTES,
    MAX_ZIP_TOTAL_SIZE_BYTES,
)
from app.core.exceptions import (
    WebhookVerificationError,
    ZipSecurityError,
)


# Webhook Signature Verification

def verify_github_signature(
    payload_body: bytes,
    signature_header: str,
    secret: str,
) -> None:
    """
    Verify a GitHub webhook HMAC-SHA256 signature.

    Uses ``hmac.compare_digest`` for constant-time comparison to prevent
    timing side-channel attacks.

    Args:
        payload_body:      The raw request body bytes (MUST be read before parsing).
        signature_header:  Value of the ``X-Hub-Signature-256`` header.
        secret:            The configured webhook secret.

    Raises:
        WebhookVerificationError: If the signature is missing, malformed, or invalid.
    """
    if not signature_header:
        raise WebhookVerificationError(
            "Missing X-Hub-Signature-256 header",
            code="MISSING_SIGNATURE",
        )

    if not signature_header.startswith(GITHUB_SIGNATURE_PREFIX):
        raise WebhookVerificationError(
            f"Signature header must start with '{GITHUB_SIGNATURE_PREFIX}'",
            code="MALFORMED_SIGNATURE",
        )

    received_sig = signature_header[len(GITHUB_SIGNATURE_PREFIX):]

    # Compute expected HMAC
    mac = hmac.new(
        key=secret.encode("utf-8"),
        msg=payload_body,
        digestmod=hashlib.sha256,
    )
    expected_sig = mac.hexdigest()

    # Constant-time comparison — NEVER use == for HMAC comparison
    if not hmac.compare_digest(expected_sig, received_sig):
        raise WebhookVerificationError(
            "Webhook signature verification failed",
            code="INVALID_SIGNATURE",
        )


# ZIP Security Helpers

def validate_zip_member_path(member_path: str) -> None:
    """
    Validate a single ZIP member path for path traversal attempts.

    Blocks:
      - Absolute paths (e.g. ``/etc/passwd``)
      - Parent directory traversal (e.g. ``../../etc/passwd``)
      - Windows-style traversal (e.g. ``..\\evil``)
      - Null bytes

    Args:
        member_path: The member name/path from the ZIP archive.

    Raises:
        ZipSecurityError: If the path is considered unsafe.
    """
    if not member_path:
        raise ZipSecurityError("ZIP member has an empty path")

    # Null byte injection
    if "\x00" in member_path:
        raise ZipSecurityError(
            f"ZIP member path contains null byte: {member_path!r}",
        )

    # Normalize and check for traversal using PurePosixPath
    normalized = PurePosixPath(member_path)

    # Absolute paths
    if normalized.is_absolute():
        raise ZipSecurityError(
            f"ZIP member has absolute path (path traversal attempt): {member_path!r}",
        )

    # Any path component that is ".."
    if any(part == ".." for part in normalized.parts):
        raise ZipSecurityError(
            f"ZIP member contains path traversal sequence: {member_path!r}",
        )

    # Windows-style backslash traversal
    if "\\" in member_path and ".." in member_path:
        raise ZipSecurityError(
            f"ZIP member contains Windows-style traversal: {member_path!r}",
        )


def validate_zip_extraction_limits(
    *,
    file_count: int,
    total_extracted_bytes: int,
    current_file_bytes: int,
    member_path: str,
) -> None:
    """
    Enforce ZIP bomb and resource-limit protections during extraction.

    Call this for each member before extracting it.

    Args:
        file_count:              Number of files already extracted.
        total_extracted_bytes:   Total bytes extracted so far.
        current_file_bytes:      Uncompressed size of the current member.
        member_path:             Path of the current member (for error context).

    Raises:
        ZipSecurityError: If any limit would be exceeded.
    """
    if file_count >= MAX_ZIP_FILE_COUNT:
        raise ZipSecurityError(
            f"ZIP archive exceeds maximum file count ({MAX_ZIP_FILE_COUNT})",
        )

    if current_file_bytes > MAX_ZIP_SINGLE_FILE_BYTES:
        raise ZipSecurityError(
            f"ZIP member '{member_path}' exceeds max single-file size "
            f"({MAX_ZIP_SINGLE_FILE_BYTES // 1024 // 1024} MB)",
        )

    if total_extracted_bytes + current_file_bytes > MAX_ZIP_TOTAL_SIZE_BYTES:
        raise ZipSecurityError(
            f"ZIP extraction would exceed total size limit "
            f"({MAX_ZIP_TOTAL_SIZE_BYTES // 1024 // 1024} MB)",
        )


def safe_extract_path(base_dir: str, member_path: str) -> str:
    """
    Resolve a ZIP member path relative to a base directory safely.

    Ensures the resolved path stays inside ``base_dir``.

    Args:
        base_dir:    Absolute path of the extraction root directory.
        member_path: Member path from the ZIP archive.

    Returns:
        Absolute resolved path for the member.

    Raises:
        ZipSecurityError: If the resolved path escapes ``base_dir``.
    """
    # Validate path components first
    validate_zip_member_path(member_path)

    base = os.path.realpath(base_dir)
    target = os.path.realpath(os.path.join(base, member_path))

    # Final check: resolved path must still be inside base_dir
    if not target.startswith(base + os.sep) and target != base:
        raise ZipSecurityError(
            f"ZIP member path escapes extraction directory: {member_path!r}",
        )

    return target


# Input Sanitization

# Pattern for a valid GitHub repository URL
_GITHUB_REPO_URL_PATTERN = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9_.\-]+)/(?P<repo>[A-Za-z0-9_.\-]+?)(?:\.git)?/?$",
)

# Pattern for a valid Git branch name (simplified)
_GIT_BRANCH_PATTERN = re.compile(
    r"^[A-Za-z0-9._/\-]+$",
)


def parse_github_url(url: str) -> tuple[str, str]:
    """
    Parse and validate a GitHub repository URL.

    Args:
        url: URL to validate (e.g. ``https://github.com/owner/repo``).

    Returns:
        Tuple of (owner, repo_name).

    Raises:
        InvalidGitHubURLError: If the URL is not a valid GitHub repo URL.
    """
    from app.core.exceptions import InvalidGitHubURLError  # local import avoids cycle

    url = url.strip()
    match = _GITHUB_REPO_URL_PATTERN.match(url)
    if not match:
        raise InvalidGitHubURLError(
            f"Not a valid GitHub repository URL: {url!r}. "
            "Expected format: https://github.com/owner/repo",
        )

    owner = match.group("owner")
    repo = match.group("repo")
    return owner, repo


def validate_branch_name(branch: str) -> str:
    """
    Validate a Git branch name.

    Args:
        branch: Branch name string.

    Returns:
        Stripped branch name if valid.

    Raises:
        ValidationError: If the branch name contains invalid characters.
    """
    from app.core.exceptions import ValidationError  # local import

    branch = branch.strip()
    if not branch:
        raise ValidationError("Branch name cannot be empty")
    if not _GIT_BRANCH_PATTERN.match(branch):
        raise ValidationError(
            f"Invalid branch name: {branch!r}. "
            "Only alphanumeric characters, dots, slashes, underscores, and hyphens are allowed.",
        )
    return branch


def sanitize_query(query: str, max_length: int = 2_000) -> str:
    """
    Sanitize and truncate a user-provided search query.

    Args:
        query:      Raw query string.
        max_length: Maximum allowed length.

    Returns:
        Stripped and truncated query.

    Raises:
        QueryTooLongError: If the query exceeds max_length after stripping.
    """
    from app.core.exceptions import QueryTooLongError  # local import

    query = query.strip()
    if len(query) > max_length:
        raise QueryTooLongError(
            f"Query length {len(query)} exceeds maximum allowed {max_length} characters",
        )
    return query
