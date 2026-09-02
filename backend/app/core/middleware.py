"""
app/core/middleware.py
FastAPI middleware for Code Explorer.

Provides:
  - Request ID injection (X-Request-ID header)
  - Request timing (X-Process-Time-Ms header)
  - Global exception handler → normalized JSON error responses
  - Never exposes internal stack traces in production
"""

from __future__ import annotations

import time
import traceback
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.exceptions import CodeExplorerException
from app.core.logging import get_logger, set_request_id

logger = get_logger(__name__)


# ── Request ID + Timing Middleware ────────────────────────────────────────────

class RequestContextMiddleware(BaseHTTPMiddleware):
    """
    Injects a unique request ID into each request and logs request/response
    metadata including processing time.

    Headers added to every response:
      - ``X-Request-ID``: The request's unique identifier.
      - ``X-Process-Time-Ms``: Time taken to process the request in milliseconds.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        # Use client-provided request ID if present, otherwise generate one
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        set_request_id(request_id)

        start_time = time.perf_counter()

        logger.info(
            "request_started",
            method=request.method,
            path=str(request.url.path),
            client=request.client.host if request.client else "unknown",
        )

        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.error(
                "request_unhandled_exception",
                path=str(request.url.path),
                duration_ms=duration_ms,
                exc_info=exc,
            )
            raise

        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-Ms"] = str(duration_ms)

        logger.info(
            "request_completed",
            method=request.method,
            path=str(request.url.path),
            status_code=response.status_code,
            duration_ms=duration_ms,
        )

        return response


# ── Error Response Builder ─────────────────────────────────────────────────────

def _build_error_response(
    *,
    status_code: int,
    error_code: str,
    message: str,
    details: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> JSONResponse:
    """Build a normalized JSON error response."""
    body: dict[str, Any] = {
        "success": False,
        "error": {
            "code": error_code,
            "message": message,
        },
    }
    if details:
        body["error"]["details"] = details
    if request_id:
        body["request_id"] = request_id

    return JSONResponse(status_code=status_code, content=body)


# ── Exception Handlers ────────────────────────────────────────────────────────

async def code_explorer_exception_handler(
    request: Request,
    exc: CodeExplorerException,
) -> JSONResponse:
    """
    Handle all CodeExplorerException subclasses and convert them to
    structured JSON error responses.

    Never exposes internal tracebacks in the response.
    """
    request_id: str = request.headers.get("X-Request-ID", "")

    logger.warning(
        "domain_exception",
        error_code=exc.code,
        message=exc.message,
        status_code=exc.http_status,
        details=exc.details,
    )

    return _build_error_response(
        status_code=exc.http_status,
        error_code=exc.code,
        message=exc.message,
        details=exc.details if exc.details else None,
        request_id=request_id,
    )


async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """
    Catch-all for unexpected exceptions.

    Logs the full traceback server-side but returns a generic error response
    to the client (no internal details exposed).
    """
    request_id: str = request.headers.get("X-Request-ID", "")

    logger.error(
        "unhandled_exception",
        path=str(request.url.path),
        method=request.method,
        exc_type=type(exc).__name__,
        traceback=traceback.format_exc(),
    )

    return _build_error_response(
        status_code=500,
        error_code="INTERNAL_ERROR",
        message="An unexpected internal error occurred. Please try again later.",
        request_id=request_id,
    )


# ── Registration Helper ───────────────────────────────────────────────────────

def register_middleware(app: FastAPI) -> None:
    """
    Register all middleware and exception handlers on the FastAPI application.

    Call this from ``app/main.py`` during application startup.
    """
    # Middleware (applied in reverse registration order by Starlette)
    app.add_middleware(RequestContextMiddleware)

    # Exception handlers
    app.add_exception_handler(CodeExplorerException, code_explorer_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)
