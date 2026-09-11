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

from app.infrastructure.qdrant.vector_repository import search_vectors
from app.modules.search.domain.search_domain import (
    RetrievedChunk,
    SearchContext,
)


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
            print(
                "DENSE SEARCH: Query vector is missing or empty"
            )
            return []

        # ---------------------------------------------------------
        # 3. DEBUG
        # ---------------------------------------------------------
        print("\n========== DENSE SEARCH DEBUG ==========")
        print("REQUEST REPOSITORY NAME:", context.repo_name)
        print("SELECTED COLLECTION:", context.qdrant_collection)
        print("DENSE SEARCH: ONLY selected collection")
        print(
            "QUERY VECTOR TYPE:",
            type(context.query_vector),
        )
        print(
            "QUERY VECTOR DIMENSION:",
            len(context.query_vector),
        )
        print(
            "QUERY VECTOR FIRST 5 VALUES:",
            context.query_vector[:5],
        )
        print(
            "QUERY VECTOR EMPTY:",
            not bool(context.query_vector),
        )
        print("========================================\n")

        # ---------------------------------------------------------
        # 4. Search Qdrant
        # ---------------------------------------------------------
        if not context.qdrant_collection:
            print("DENSE SEARCH: No selected collection")
            return []

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
                    chunk_hash=payload.get(
                        "chunk_hash",
                        "",
                    ),
                    file_path=payload.get(
                        "file_path",
                        "",
                    ),
                    content=payload.get(
                        "code",
                        payload.get(
                            "content",
                            "",
                        ),
                    ),
                    score=float(point.score),
                    metadata=payload,
                )
            )

        # ---------------------------------------------------------
        # 6. Debug results
        # ---------------------------------------------------------

        print(
            f"DENSE SEARCH: Retrieved "
            f"{len(chunks)} chunks from Qdrant"
        )

        for index, chunk in enumerate(
            chunks[:5],
            start=1,
        ):
            print(
                f"\n--- Dense Result {index} ---"
            )

            print(
                "File:",
                chunk.file_path,
            )

            print(
                "Score:",
                chunk.score,
            )

            print(
                "Chunk Hash:",
                chunk.chunk_hash,
            )

            print(
                "Repo:",
                chunk.metadata.get(
                    "repo_name",
                    "",
                ),
            )

            print(
                "Code:",
                chunk.content[:500],
            )

        return chunks