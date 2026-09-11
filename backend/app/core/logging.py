
"""
app/core/logging.py

Centralized application logging configuration.

Provides:
- Console logging with color-aware rendering
- File logging with rotating file handler
- Structured logging using structlog
- Request ID support via context vars
- Secret redaction
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Any

import structlog


# ============================================================
# LOG FILE CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[2]

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "app.log"


# ============================================================
# REQUEST ID
# ============================================================

def set_request_id(request_id: str) -> None:
    """
    Store the request ID in structlog context.

    The request ID will automatically be included
    in subsequent logs for the current request.
    """
    structlog.contextvars.bind_contextvars(
        request_id=request_id
    )


# ============================================================
# SECRET REDACTION
# ============================================================

_SECRET_KEYS: frozenset[str] = frozenset(
    {
        "api_key",
        "token",
        "access_token",
        "refresh_token",
        "secret",
        "password",
        "passwd",
        "authorization",
        "github_token",
        "jina_api_key",
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


# ============================================================
# CONFIGURE LOGGING
# ============================================================

def configure_logging(
    *,
    json_logs: bool | None = None,
    log_level: str = "INFO",
) -> None:
    """
    Configure structlog and standard library logging integration.

    Sets up:
    - Console handler (color-aware in dev, JSON in prod)
    - Rotating file handler (always JSON for machine readability)
    - Structlog processors with secret redaction and request ID support
    """
    if json_logs is None:
        json_logs = os.environ.get("APP_ENV", "development") == "production"

    level = getattr(logging, log_level.upper(), logging.INFO)

    # Ensure stdout/stderr handle UTF-8 on Windows
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    # --------------------------------------------------------
    # Console handler
    # --------------------------------------------------------

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)

    # --------------------------------------------------------
    # File handler (rotating)
    # --------------------------------------------------------

    file_handler = logging.handlers.RotatingFileHandler(
        filename=LOG_FILE,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(level)

    # --------------------------------------------------------
    # Shared structlog processors
    # --------------------------------------------------------

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        _scrub_secrets,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    # --------------------------------------------------------
    # Renderers
    # --------------------------------------------------------

    if json_logs:
        console_renderer: Any = structlog.processors.JSONRenderer()
    else:
        use_colors = (
            sys.platform != "win32"
            or "WT_SESSION" in os.environ
            or "TERM" in os.environ
        )
        console_renderer = structlog.dev.ConsoleRenderer(colors=use_colors)

    # File output is always JSON for machine readability
    file_renderer: Any = structlog.processors.JSONRenderer()

    # --------------------------------------------------------
    # Structlog configuration
    # --------------------------------------------------------

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )

    # --------------------------------------------------------
    # Console formatter
    # --------------------------------------------------------

    console_formatter = structlog.stdlib.ProcessorFormatter(
        processor=console_renderer,
        foreign_pre_chain=shared_processors,
    )
    console_handler.setFormatter(console_formatter)

    # --------------------------------------------------------
    # File formatter
    # --------------------------------------------------------

    file_formatter = structlog.stdlib.ProcessorFormatter(
        processor=file_renderer,
        foreign_pre_chain=shared_processors,
    )
    file_handler.setFormatter(file_formatter)

    # --------------------------------------------------------
    # Root logger
    # --------------------------------------------------------

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    # --------------------------------------------------------
    # Silence noisy third-party loggers
    # --------------------------------------------------------

    for noisy in ("httpx", "httpcore", "urllib3", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Ensure app & uvicorn loggers output at configured level
    logging.getLogger("app").setLevel(level)
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)


# ============================================================
# LOGGER
# ============================================================

def get_logger(
    name: str | None = None,
):
    """
    Return a structlog logger bound to the given name.

    Auto-configures logging with defaults if not already configured.
    """
    if not structlog.is_configured():
        configure_logging()
    return structlog.get_logger(name)
