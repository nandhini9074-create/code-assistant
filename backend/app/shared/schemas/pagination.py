"""
app/shared/schemas/pagination.py
Pagination schemas.
"""

from typing import Generic, TypeVar

from pydantic import Field

from app.shared.schemas.base import BaseSchema

T = TypeVar("T")


class PaginationParams(BaseSchema):
    """Common pagination parameters for API requests."""
    page: int = Field(1, ge=1, description="Page number, starting from 1.")
    size: int = Field(50, ge=1, le=100, description="Items per page (max 100).")


class PaginatedResponse(BaseSchema, Generic[T]):
    """Standard paginated response envelope."""
    items: list[T]
    total: int = Field(..., description="Total number of items across all pages.")
    page: int = Field(..., description="Current page number.")
    size: int = Field(..., description="Current page size.")
    pages: int = Field(..., description="Total number of pages.")
