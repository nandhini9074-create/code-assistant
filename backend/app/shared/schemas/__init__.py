"""
app/shared/schemas/__init__.py
"""
from app.shared.schemas.base import BaseSchema
from app.shared.schemas.pagination import PaginatedResponse, PaginationParams

__all__ = ["BaseSchema", "PaginatedResponse", "PaginationParams"]
