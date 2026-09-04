"""
app/modules/search/schemas/search_schema.py
Schemas for the search module.
"""

from typing import Any

from pydantic import Field

from app.shared.schemas.base import BaseSchema


class SearchRequest(BaseSchema):
    """Request to perform a code search."""
    repo_name: str
    feature: str | None = None
    query: str = Field(..., min_length=3, max_length=1000)
    intent_hint: str | None = None


class EvidenceItem(BaseSchema):
    """An item of evidence used to generate the response."""
    file_path: str
    snippet: str
    score: float


class SearchResponse(BaseSchema):
    """Response containing search analysis and evidence."""
    intent: str
    analysis: dict[str, Any]
    evidence: list[EvidenceItem]
