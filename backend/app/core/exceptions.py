"""
app/core/exceptions.py
Centralized exception hierarchy for Code Explorer.

All application exceptions inherit from CodeExplorerException.
HTTP mapping is handled by middleware / exception handlers in app/core/middleware.py.
"""

from __future__ import annotations

from typing import Any


# ── Base ──────────────────────────────────────────────────────────────────────

class CodeExplorerException(Exception):
    """
    Base exception for all Code Explorer domain errors.

    Attributes:
        message:   Human-readable error description.
        code:      Machine-readable error code for clients.
        details:   Optional extra context (never contains secrets).
        http_status: Suggested HTTP status code when raised in an API context.
    """

    http_status: int = 500
    code: str = "INTERNAL_ERROR"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.details: dict[str, Any] = details or {}

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(code={self.code!r}, message={self.message!r})"


# ── 400 Bad Request ───────────────────────────────────────────────────────────

class ValidationError(CodeExplorerException):
    """Input validation failed."""

    http_status = 400
    code = "VALIDATION_ERROR"


class InvalidGitHubURLError(ValidationError):
    """The provided GitHub URL is not a valid repository URL."""

    code = "INVALID_GITHUB_URL"


class InvalidZIPError(ValidationError):
    """The uploaded file is not a valid ZIP archive."""

    code = "INVALID_ZIP"


class ZipSecurityError(ValidationError):
    """ZIP archive failed security validation (path traversal, bomb, etc.)."""

    code = "ZIP_SECURITY_ERROR"


class UnsupportedLanguageError(ValidationError):
    """File language is not supported for AST chunking."""

    code = "UNSUPPORTED_LANGUAGE"


class FileTooLargeError(ValidationError):
    """File exceeds the maximum allowed size for processing."""

    code = "FILE_TOO_LARGE"


class QueryTooLongError(ValidationError):
    """Search query exceeds the maximum allowed length."""

    code = "QUERY_TOO_LONG"


class MalformedRequestError(ValidationError):
    """Request is structurally malformed and cannot be parsed."""

    code = "MALFORMED_REQUEST"


# ── 401 Unauthorized ──────────────────────────────────────────────────────────

class WebhookVerificationError(CodeExplorerException):
    """GitHub webhook HMAC-SHA256 signature verification failed."""

    http_status = 401
    code = "WEBHOOK_VERIFICATION_FAILED"


# ── 403 Forbidden ─────────────────────────────────────────────────────────────

class AccessDeniedError(CodeExplorerException):
    """The caller does not have permission to access this resource."""

    http_status = 403
    code = "ACCESS_DENIED"


# ── 404 Not Found ─────────────────────────────────────────────────────────────

class RepositoryNotFoundError(CodeExplorerException):
    """Repository not found in the registry."""

    http_status = 404
    code = "REPOSITORY_NOT_FOUND"

    def __init__(self, repo_id: str | None = None, url: str | None = None) -> None:
        identifier = repo_id or url or "unknown"
        super().__init__(f"Repository not found: {identifier}")
        self.details = {"repo_id": repo_id, "url": url}


class JobNotFoundError(CodeExplorerException):
    """Ingestion job not found."""

    http_status = 404
    code = "JOB_NOT_FOUND"

    def __init__(self, job_id: str) -> None:
        super().__init__(f"Job not found: {job_id}")
        self.details = {"job_id": job_id}


class FileNotFoundInRegistryError(CodeExplorerException):
    """File record not found in the file registry."""

    http_status = 404
    code = "FILE_NOT_IN_REGISTRY"


# ── 409 Conflict ──────────────────────────────────────────────────────────────

class RepositoryAlreadyExistsError(CodeExplorerException):
    """A repository with this URL is already registered."""

    http_status = 409
    code = "REPOSITORY_ALREADY_EXISTS"


class DuplicateWebhookDeliveryError(CodeExplorerException):
    """Webhook delivery ID already processed (idempotency guard)."""

    http_status = 409
    code = "DUPLICATE_WEBHOOK_DELIVERY"

    def __init__(self, delivery_id: str) -> None:
        super().__init__(f"Webhook delivery already processed: {delivery_id}")
        self.details = {"delivery_id": delivery_id}


# ── 422 Unprocessable ─────────────────────────────────────────────────────────

class IngestionError(CodeExplorerException):
    """Ingestion pipeline encountered an unrecoverable error."""

    http_status = 422
    code = "INGESTION_ERROR"


class ChunkingError(IngestionError):
    """AST chunking stage failed for a file."""

    code = "CHUNKING_ERROR"


# ── 429 Rate Limited ─────────────────────────────────────────────────────────

class RateLimitError(CodeExplorerException):
    """External API rate limit hit (GitHub, Voyage, Qwen)."""

    http_status = 429
    code = "RATE_LIMIT_ERROR"

    def __init__(self, service: str, retry_after: float | None = None) -> None:
        msg = f"Rate limit reached for service: {service}"
        if retry_after:
            msg += f". Retry after {retry_after:.0f}s"
        super().__init__(msg)
        self.details = {"service": service, "retry_after": retry_after}


# ── 502 Bad Gateway (upstream failures) ──────────────────────────────────────

class GitHubAPIError(CodeExplorerException):
    """GitHub API returned an unexpected error response."""

    http_status = 502
    code = "GITHUB_API_ERROR"

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        *,
        endpoint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.details = {"github_status_code": status_code, "endpoint": endpoint}


class GitHubNotFoundError(GitHubAPIError):
    """GitHub returned 404 for a repository, tree, or blob."""

    code = "GITHUB_NOT_FOUND"
    http_status = 404


class GitHubRateLimitError(GitHubAPIError, RateLimitError):
    """GitHub API rate limit exceeded."""

    code = "GITHUB_RATE_LIMIT"
    http_status = 429


class EmbeddingError(CodeExplorerException):
    """Voyage embedding API returned an error or timed out."""

    http_status = 502
    code = "EMBEDDING_ERROR"


class LLMError(CodeExplorerException):
    """Qwen (or other configured) LLM returned an error or timed out."""

    http_status = 502
    code = "LLM_ERROR"


class LLMParseError(LLMError):
    """LLM returned a response that could not be parsed into the expected schema."""

    code = "LLM_PARSE_ERROR"


# ── 503 Service Unavailable ───────────────────────────────────────────────────

class QdrantError(CodeExplorerException):
    """Qdrant vector database is unreachable or returned an error."""

    http_status = 503
    code = "QDRANT_ERROR"


class DatabaseError(CodeExplorerException):
    """PostgreSQL is unreachable or returned an unexpected error."""

    http_status = 503
    code = "DATABASE_ERROR"


class RedisError(CodeExplorerException):
    """Redis is unreachable or returned an unexpected error."""

    http_status = 503
    code = "REDIS_ERROR"


class CeleryError(CodeExplorerException):
    """Celery broker is unreachable or task submission failed."""

    http_status = 503
    code = "CELERY_ERROR"


# ── Search-specific ───────────────────────────────────────────────────────────

class InsufficientEvidenceError(CodeExplorerException):
    """
    Retrieval did not return enough evidence to support LLM analysis.
    The system must NOT call the LLM and must return a safe response.
    """

    http_status = 200  # Not an error to the client — returns a structured low-confidence response
    code = "INSUFFICIENT_EVIDENCE"


class RetrievalError(CodeExplorerException):
    """Code retrieval pipeline failed unexpectedly."""

    http_status = 500
    code = "RETRIEVAL_ERROR"


class ValidationEvidenceError(CodeExplorerException):
    """
    LLM output validation failed — the LLM referenced files/functions
    that do not exist in retrieved evidence (hallucination detected).
    """

    http_status = 200  # Returns a safe response rather than an HTTP error
    code = "HALLUCINATION_DETECTED"


# ── Configuration ─────────────────────────────────────────────────────────────

class ConfigurationError(CodeExplorerException):
    """Required configuration is missing or invalid."""

    http_status = 500
    code = "CONFIGURATION_ERROR"
