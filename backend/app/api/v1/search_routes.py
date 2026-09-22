
"""
app/api/v1/search_routes.py
Search API routes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import (
    get_query_understanding_service,
    get_search_service,
)
from app.modules.search.schemas.search_schema import (
    QueryUnderstandingResponse,
    SearchRequest,
    SearchResponse,
)
from app.modules.search.service.query_understanding_service import (
    QueryUnderstandingService,
)
from app.modules.search.service.search_service import SearchService


router = APIRouter(prefix="/search", tags=["Search"])



@router.post("/", response_model=SearchResponse)
async def search_repository(
    request: SearchRequest,
    search_service: SearchService = Depends(get_search_service),
) -> SearchResponse:
    """
    Perform a semantic code search against an indexed repository.
    Runs the complete retrieval + LLM analysis pipeline.
    """
    result = await search_service.run_pipeline(
        repo_id=request.repo_id,
        repo_name=request.repo_name,
        query=request.query,
    )

    if not result.success:
        error_msg = result.error_message or "Search execution failed"

        if "not found" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_msg,
            )

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg,
        )

    return result.response