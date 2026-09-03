"""
app/api/v1/search.py
API endpoints for code exploration and semantic search.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models.repository import Repository
from app.infrastructure.database.session import get_db
from app.modules.analysis.file_analyzer import analyze_chunks_for_intent
from app.modules.embedding.service.embedding_service import generate_embeddings
from app.infrastructure.qdrant.vector_repository import search_vectors

router = APIRouter(prefix="/search", tags=["Search"])


class SearchQuery(BaseModel):
    query: str
    intent: str
    limit: int = 5
    score_threshold: float = 0.6


@router.post("/{repo_id}")
async def semantic_search(
    repo_id: uuid.UUID,
    payload: SearchQuery,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Perform a semantic search in a repository and analyze the results based on intent.
    """
    repo = await db.get(Repository, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found.")
        
    # 1. Embed the search query
    query_vectors = await generate_embeddings([payload.query], input_type="query")
    if not query_vectors:
        raise HTTPException(status_code=500, detail="Failed to generate query embedding.")
        
    query_vector = query_vectors[0]
    
    # 2. Search Qdrant
    scored_points = await search_vectors(
        collection_name=repo.qdrant_collection,
        query_vector=query_vector,
        limit=payload.limit,
        repo_id=str(repo.id),
        score_threshold=payload.score_threshold,
    )
    
    if not scored_points:
        return {
            "results": [],
            "analysis": {
                "summary": "No relevant code chunks found.",
                "key_findings": [],
                "files_referenced": [],
                "confidence_score": 0.0,
            }
        }
        
    # 3. Format chunks for analysis
    chunks_for_analysis = []
    for point in scored_points:
        payload_data = point.payload or {}
        chunks_for_analysis.append({
            "file_path": payload_data.get("file_path", "unknown"),
            "start_line": payload_data.get("start_line", 0),
            "end_line": payload_data.get("end_line", 0),
            "raw_code": payload_data.get("content", ""),
            "score": point.score,
        })
        
    # 4. Run intent analysis via LLM
    analysis_result = await analyze_chunks_for_intent(
        intent=payload.intent,
        query=payload.query,
        chunks=chunks_for_analysis,
    )
    
    return {
        "results": chunks_for_analysis,
        "analysis": analysis_result,
    }
