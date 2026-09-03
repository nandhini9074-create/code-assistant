"""
app/infrastructure/qdrant/vector_repository.py
Repository for interacting with Qdrant vectors and payloads.
"""

from __future__ import annotations

import uuid
from typing import Any

from qdrant_client.http import models as qmodels

from app.core.constants import QDRANT_POINT_ID_NAMESPACE
from app.core.logging import get_logger
from app.infrastructure.qdrant.client import get_qdrant_client

logger = get_logger(__name__)

# UUID namespace for deterministic point IDs
_NAMESPACE = uuid.UUID(QDRANT_POINT_ID_NAMESPACE)


def generate_point_id(repo_id: str, file_path: str, chunk_hash: str) -> str:
    """
    Generate a deterministic UUID (v5) for a Qdrant point based on
    the repository ID, file path, and chunk hash.
    """
    name = f"{repo_id}:{file_path}:{chunk_hash}"
    return str(uuid.uuid5(_NAMESPACE, name))


async def upsert_vectors(
    collection_name: str,
    points: list[qmodels.PointStruct],
) -> None:
    """
    Upsert a batch of vectors into Qdrant.
    """
    if not points:
        return

    client = get_qdrant_client()
    try:
        await client.upsert(
            collection_name=collection_name,
            points=points,
        )
    except Exception as exc:
        logger.error("qdrant_upsert_failed", collection=collection_name, count=len(points), exc_info=exc)
        raise


async def search_vectors(
    collection_name: str,
    query_vector: list[float],
    limit: int,
    repo_id: str | None = None,
    file_path: str | None = None,
    score_threshold: float | None = None,
) -> list[qmodels.ScoredPoint]:
    """
    Search for similar vectors in Qdrant.
    """
    client = get_qdrant_client()
    
    # Build filter conditions
    must_conditions = []
    
    if repo_id:
        must_conditions.append(
            qmodels.FieldCondition(
                key="repo_id",
                match=qmodels.MatchValue(value=repo_id),
            )
        )
        
    if file_path:
        must_conditions.append(
            qmodels.FieldCondition(
                key="file_path",
                match=qmodels.MatchValue(value=file_path),
            )
        )
        
    query_filter = None
    if must_conditions:
        query_filter = qmodels.Filter(must=must_conditions)

    try:
        return await client.search(
            collection_name=collection_name,
            query_vector=query_vector,
            query_filter=query_filter,
            limit=limit,
            score_threshold=score_threshold,
            with_payload=True,
        )
    except Exception as exc:
        logger.error("qdrant_search_failed", collection=collection_name, exc_info=exc)
        raise


async def delete_vectors_by_file(
    collection_name: str,
    repo_id: str,
    file_path: str,
) -> None:
    """
    Delete all vectors associated with a specific file in a repository.
    """
    client = get_qdrant_client()
    
    try:
        await client.delete(
            collection_name=collection_name,
            points_selector=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="repo_id",
                        match=qmodels.MatchValue(value=repo_id),
                    ),
                    qmodels.FieldCondition(
                        key="file_path",
                        match=qmodels.MatchValue(value=file_path),
                    ),
                ]
            ),
        )
    except Exception as exc:
        logger.error("qdrant_delete_file_failed", collection=collection_name, file=file_path, exc_info=exc)
        raise


async def delete_vectors_by_repo(
    collection_name: str,
    repo_id: str,
) -> None:
    """
    Delete all vectors associated with a repository.
    """
    client = get_qdrant_client()
    
    try:
        await client.delete(
            collection_name=collection_name,
            points_selector=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="repo_id",
                        match=qmodels.MatchValue(value=repo_id),
                    ),
                ]
            ),
        )
    except Exception as exc:
        logger.error("qdrant_delete_repo_failed", collection=collection_name, repo_id=repo_id, exc_info=exc)
        raise
