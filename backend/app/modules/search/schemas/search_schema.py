
"""
app/modules/search/schemas/search_schema.py

Schemas for the search module.
"""

from typing import Any

from pydantic import Field

from app.shared.schemas.base import BaseSchema


class SearchRequest(BaseSchema):
    """Request containing the repository and user's query."""

    repo_name: str
    query: str = Field(..., min_length=3, max_length=1000)


class QueryUnderstandingResponse(BaseSchema):
    """
    Response for the initial query-understanding pipeline.

    This is intentionally limited to:
    - intent classification
    - explicit parameter identification
    - query preprocessing
    """

    success: bool
    query: str

    intent: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = None

    keywords: list[str] = Field(default_factory=list)
    identifiers: list[str] = Field(default_factory=list)
    file_paths: list[str] = Field(default_factory=list)
    repo_hint: str | None = None
    language_hint: str | None = None

    error: str | None = None


class EvidenceItem(BaseSchema):
    """An item of evidence used to generate the response."""

    file_path: str
    snippet: str
    score: float


class SearchResponse(BaseSchema):
    """Compact public response for Code Explorer / RepoLens."""

    intent: str

    repository: dict[str, Any] | None = None

    target: dict[str, Any] | None = None

    requirement: str | None = None

    suggestion: str | None = None

    confidence: str | None = None

    code_context: list[dict[str, Any]] = Field(default_factory=list)

    early_exit: dict[str, Any] | None = None

