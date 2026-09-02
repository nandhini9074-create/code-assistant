"""
app/core/logging.py
Structured logging configuration for Code Explorer.

Uses structlog for JSON-structured logs with request-scoped context vars.
Never logs secrets, API keys, or tokens.
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import Any
from uuid import uuid4

import structlog

# ── Context Variables (per-request, async-safe) ───────────────────────────────

_request_id_var: ContextVar[str] = ContextVar("request_id", default="")
_repo_id_var: ContextVar[str] = ContextVar("repo_id", default="")
_job_id_var: ContextVar[str] = ContextVar("job_id", default="")
_webhook_delivery_id_var: ContextVar[str] = ContextVar("webhook_delivery_id", default="")


def set_request_id(request_id: str | None = None) -> str:
    """Set request ID in context. Generates a new UUID if not provided."""
    rid = request_id or str(uuid4())
    _request_id_var.set(rid)
    return rid


def set_repo_id(repo_id: str) -> None:
    """Bind repo_id to the current async context."""
    _repo_id_var.set(repo_id)


def set_job_id(job_id: str) -> None:
    """Bind job_id to the current async context."""
    _job_id_var.set(job_id)


def set_webhook_delivery_id(delivery_id: str) -> None:
    """Bind webhook delivery ID to the current async context."""
    _webhook_delivery_id_var.set(delivery_id)


def get_request_id() -> str:
    return _request_id_var.get()


def get_repo_id() -> str:
    return _repo_id_var.get()


def get_job_id() -> str:
    return _job_id_var.get()


def get_webhook_delivery_id() -> str:
    return _webhook_delivery_id_var.get()


# ── Context Injector Processor ────────────────────────────────────────────────

def _inject_context(
    _logger: Any,
    _method: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """
    Structlog processor that injects async-safe context variables
    (request_id, repo_id, job_id, webhook_delivery_id) into every log record.
    """
    if rid := _request_id_var.get():
        event_dict["request_id"] = rid
    if repo := _repo_id_var.get():
        event_dict["repo_id"] = repo
    if job := _job_id_var.get():
        event_dict["job_id"] = job
    if delivery := _webhook_delivery_id_var.get():
        event_dict["webhook_delivery_id"] = delivery
    return event_dict


# ── Secret Scrubber ───────────────────────────────────────────────────────────

_SECRET_KEYS: frozenset[str] = frozenset(
    {
        "api_key",
        "token",
        "secret",
        "password",
        "passwd",
        "authorization",
        "github_token",
        "voyage_api_key",
        "qwen_api_key",
        "webhook_secret",
        "app_secret_key",
        "database_url",
        "redis_url",
        "celery_broker_url",
    }
)


def _scrub_secrets(
    _logger: Any,
    _method: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """
    Structlog processor that redacts known secret keys from log records.
    Prevents accidental credential leakage in logs.
    """
    for key in list(event_dict.keys()):
        if any(secret in key.lower() for secret in _SECRET_KEYS):
            event_dict[key] = "***REDACTED***"
    return event_dict


# ── Setup ─────────────────────────────────────────────────────────────────────

def configure_logging(*, json_logs: bool = True, log_level: str = "INFO") -> None:
    """
    Configure structlog and the standard library logging integration.

    Call once at application startup (in app/main.py lifespan).

    Args:
        json_logs:  Render logs as JSON (production). False = pretty console.
        log_level:  Minimum log level (e.g. "DEBUG", "INFO", "WARNING").
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    # Standard library logging handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    logging.basicConfig(
        level=level,
        handlers=[handler],
        format="%(message)s",
    )

    # Silence noisy third-party loggers
    for noisy in ("httpx", "httpcore", "uvicorn.access", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Shared processors
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        _inject_context,
        _scrub_secrets,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_logs:
        # Production: JSON output (parseable by log aggregators)
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        # Development: colorized human-readable output
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )
    handler.setFormatter(formatter)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """
    Get a structlog logger bound to the given name.

    Usage::

        from app.core.logging import get_logger
        logger = get_logger(__name__)
        logger.info("file_processed", file_path="src/main.py", duration_ms=42)
    """
    return structlog.get_logger(name)
