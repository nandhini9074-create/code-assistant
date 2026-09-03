"""
app/api/v1/search_routes.py
Search API routes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.modules.search.schemas.search_schema import SearchRequest, SearchResponse

router = APIRouter(prefix="/search", tags=["Search"])


@router.post("/", response_model=SearchResponse)
async def search_repository(
    request: SearchRequest,
) -> SearchResponse:
    """
    Perform a semantic code search against an indexed repository.
    Runs the full 9-stage retrieval + LLM analysis pipeline.
    Full DI wiring for SearchService is deferred until Qwen provider is configured.
    """
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Search service not yet configured. Wire SearchService via dependencies.py.",
    )
