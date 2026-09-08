from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.session import get_db
from app.modules.search.application.search_service import SearchService

router = APIRouter(prefix="/search", tags=["Search"])


class SearchQuery(BaseModel):
    query: str


@router.post("/{repo_id}")
async def semantic_search(
    repo_id: uuid.UUID,
    payload: SearchQuery,
    db: AsyncSession = Depends(get_db),
) -> dict:

    search_service = SearchService(db=db)

    result = await search_service.run_pipeline(
        repo_name=str(repo_name),
        query=payload.query,
    )

    return result