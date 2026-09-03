"""
app/shared/responses/api_response.py
Standardized API response envelopes.
"""

from typing import Any, Generic, TypeVar

from app.shared.schemas.base import BaseSchema

T = TypeVar("T")


class ErrorDetails(BaseSchema):
    """Details for an error response."""
    code: str
    message: str
    details: dict[str, Any] | None = None


class APIResponse(BaseSchema, Generic[T]):
    """Standard success response envelope."""
    success: bool = True
    data: T
    request_id: str | None = None


class ErrorResponse(BaseSchema):
    """Standard error response envelope."""
    success: bool = False
    error: ErrorDetails
    request_id: str | None = None


class JobResponse(BaseSchema):
    """Standard response for async jobs."""
    success: bool = True
    job_id: str
    message: str
    request_id: str | None = None
