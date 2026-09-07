
"""
app/core/logging.py

Centralized application logging configuration.

Provides:
- Console logging
- File logging
- Structured logging using structlog
- Request ID support
- Secret redaction
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

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

def _scrub_secrets(
    logger,
    method_name,
    event_dict,
):
    """
    Remove sensitive values from logs.
    """

    sensitive_keys = {
        "password",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "secret",
        "authorization",
    }

    for key in list(event_dict.keys()):
        if key.lower() in sensitive_keys:
            event_dict[key] = "***REDACTED***"

    return event_dict


# ============================================================
# CONFIGURE LOGGING
# ============================================================

def configure_logging(
    *,
    json_logs: bool = False,
    log_level: str = "INFO",
) -> None:

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    level = getattr(
        logging,
        log_level.upper(),
        logging.INFO,
    )

    # --------------------------------------------------------
    # Console handler
    # --------------------------------------------------------

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)

    # --------------------------------------------------------
    # File handler
    # --------------------------------------------------------

    file_handler = logging.handlers.RotatingFileHandler(
        filename=LOG_FILE,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )

    file_handler.setLevel(level)

    # --------------------------------------------------------
    # Structlog processors
    # --------------------------------------------------------

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        _scrub_secrets,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(
            fmt="iso",
            utc=True,
        ),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    # --------------------------------------------------------
    # Console renderer
    # --------------------------------------------------------

    if json_logs:
        console_renderer = structlog.processors.JSONRenderer()
    else:
        console_renderer = structlog.dev.ConsoleRenderer()

    # --------------------------------------------------------
    # File renderer
    # --------------------------------------------------------

    file_renderer = structlog.processors.JSONRenderer()

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
        cache_logger_on_first_use=True,
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
    # Reduce noisy library logs
    # --------------------------------------------------------

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


# ============================================================
# LOGGER
# ============================================================

def get_logger(
    name: str | None = None,
):
    """
    Return a structlog logger.
    """

    return structlog.get_logger(name)

