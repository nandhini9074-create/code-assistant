"""
app/modules/search/retrieval/dense_search.py

Dense vector retrieval using the pre-computed Jina query embedding
and Qdrant similarity search.

The current architecture uses multiple Qdrant collections.
Each repository has its own collection following the convention:

    repo_owner_repositoryname

For global search, all Qdrant collections are searched.

PostgreSQL repository identification is not required.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.infrastructure.qdrant.vector_repository import search_vectors
from app.modules.search.domain.search_domain import (
    RetrievedChunk,
    SearchContext,
)

logger = get_logger(__name__)


class DenseSearch:
    """Perform dense vector retrieval against Qdrant."""

    async def search(
        self,
        context: SearchContext,
        limit: int = 20,
    ) -> list[RetrievedChunk]:
        """
        Retrieve the most similar code chunks from Qdrant.

        When context.qdrant_collection is None, search_vectors()
        performs a global search across all Qdrant collections.

        Each repository has its own Qdrant collection using the
        repo_owner_repositoryname naming convention.

        Example payload:

            {
                "repo_name": "demo10-transaction",
                "repo_id": "...",
                "file_path": "...",
                "function_name": "...",
                "code": "..."
            }
        """

        # ---------------------------------------------------------
        # 1. Validate search limit
        # ---------------------------------------------------------
        if limit <= 0:
            return []

        # ---------------------------------------------------------
        # 2. Validate query embedding
        # ---------------------------------------------------------
        if not context.query_vector:
            logger.warning(
                "dense_search_skipped",
                reason="query_vector_missing_or_empty",
                repo_name=context.repo_name,
            )
            return []

        # ---------------------------------------------------------
        # 3. Validate collection
        # ---------------------------------------------------------
        if not context.qdrant_collection:
            logger.warning(
                "dense_search_skipped",
                reason="no_qdrant_collection_selected",
                repo_name=context.repo_name,
            )
            return []

        logger.info(
            "dense_search_started",
            repo_name=context.repo_name,
            collection=context.qdrant_collection,
            vector_dim=len(context.query_vector),
            limit=limit,
        )

        # ---------------------------------------------------------
        # 4. Search Qdrant
        # ---------------------------------------------------------
        scored_points = await search_vectors(
            collection_name=context.qdrant_collection,
            query_vector=context.query_vector,
            limit=limit,
        )

        # ---------------------------------------------------------
        # 5. Convert Qdrant points into RetrievedChunk objects
        # ---------------------------------------------------------
        chunks: list[RetrievedChunk] = []

        for point in scored_points or []:
            payload = point.payload or {}

            chunks.append(
                RetrievedChunk(
                    chunk_hash=payload.get("chunk_hash", ""),
                    file_path=payload.get("file_path", ""),
                    content=payload.get(
                        "code",
                        payload.get("content", ""),
                    ),
                    score=float(point.score),
                    metadata=payload,
                )
            )

        logger.info(
            "dense_search_completed",
            repo_name=context.repo_name,
            collection=context.qdrant_collection,
            chunks_retrieved=len(chunks),
            top_score=round(chunks[0].score, 4) if chunks else None,
        )

        return chunks