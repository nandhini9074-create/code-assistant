"""
app/infrastructure/qdrant/vector_repository.py

Repository for interacting with Qdrant vectors and payloads.

Search supports searching across all repository-specific Qdrant
collections.

Each repository has its own Qdrant collection following the naming
convention:

    repo_owner_repositoryname

For global search, all Qdrant collections are searched and the best
results are combined and ranked globally.

PostgreSQL repository identification is not required for retrieval.
"""

from __future__ import annotations

import uuid

from qdrant_client.http import models as qmodels

from app.core.constants import QDRANT_POINT_ID_NAMESPACE
from app.core.logging import get_logger
from app.infrastructure.qdrant.client import get_qdrant_client

logger = get_logger(__name__)


# ================================================================
# UUID namespace for deterministic point IDs
# ================================================================

_NAMESPACE = uuid.UUID(QDRANT_POINT_ID_NAMESPACE)


# ================================================================
# Point ID generation
# ================================================================

def generate_point_id(
    repo_id: str,
    file_path: str,
    chunk_hash: str,
) -> str:
    """
    Generate a deterministic UUID (v5) for a Qdrant point.

    The same repository, file and chunk hash will always produce
    the same point ID.
    """

    name = f"{repo_id}:{file_path}:{chunk_hash}"

    return str(
        uuid.uuid5(
            _NAMESPACE,
            name,
        )
    )


# ================================================================
# Upsert vectors
# ================================================================

async def upsert_vectors(
    collection_name: str,
    points: list[qmodels.PointStruct],
) -> None:
    """
    Upsert a batch of vectors into a Qdrant collection.
    """

    if not points:
        return

    client = get_qdrant_client()

    try:
        await client.upsert(
            collection_name=collection_name,
            points=points,
        )

    except Exception:
        logger.exception(
            "qdrant_upsert_failed",
            collection=collection_name,
            count=len(points),
        )
        raise


# ================================================================
# Get all collections
# ================================================================

async def get_all_collections() -> list[str]:
    """
    Return all Qdrant collection names.

    Each repository has its own collection.

    Example:

        owner_demo10-transaction
        owner_payment-service
        owner_auth-service

    The search pipeline can therefore perform global search across
    all repositories without requiring PostgreSQL repository
    identification.
    """

    client = get_qdrant_client()

    try:
        collections_response = await client.get_collections()

        collection_names = [
            collection.name
            for collection in collections_response.collections
        ]

        print(
            "\n========== QDRANT COLLECTIONS =========="
        )

        print(
            "TOTAL COLLECTIONS:",
            len(collection_names),
        )

        for name in collection_names:
            print(
                "COLLECTION:",
                name,
            )

        print(
            "========================================\n"
        )

        return collection_names

    except Exception:
        logger.exception(
            "qdrant_get_collections_failed"
        )
        raise


# ================================================================
# Search vectors
# ================================================================

async def search_vectors(
    query_vector: list[float],
    limit: int,
    collection_name: str | None = None,
    repo_name: str | None = None,
    repo_id: str | None = None,
    file_path: str | None = None,
    score_threshold: float | None = None,
) -> list[qmodels.ScoredPoint]:
    """
    Search Qdrant for similar vectors.

    Behaviour:

    1. If collection_name is provided:
           Search only that collection.

    2. If collection_name is None:
           Search ALL Qdrant collections.

    3. If repo_name or repo_id is provided:
           Apply the corresponding payload filter.

    4. If file_path is provided:
           Apply a file-path payload filter.

    5. Results from all searched collections are combined.

    6. Results are globally sorted by similarity score.

    7. Only the global top `limit` results are returned.

    PostgreSQL is not used.
    """

    # ------------------------------------------------------------
    # Validate limit
    # ------------------------------------------------------------

    if limit <= 0:
        return []

    # ------------------------------------------------------------
    # Validate query vector
    # ------------------------------------------------------------

    if not query_vector:
        return []

    client = get_qdrant_client()

    # ------------------------------------------------------------
    # Determine collections to search
    # ------------------------------------------------------------

    if collection_name:
        # Specific collection search
        collections = [collection_name]
        search_mode = "SINGLE_COLLECTION"
    else:
        print("QDRANT SEARCH: ALL_COLLECTIONS mode disabled. Specific collection required.")
        return []

    # ------------------------------------------------------------
    # No collections available
    # ------------------------------------------------------------

    if not collections:

        print(
            "QDRANT SEARCH: No collections found"
        )

        return []

    # ------------------------------------------------------------
    # Debug information
    # ------------------------------------------------------------

    print(
        "\n========== QDRANT SEARCH =========="
    )

    print(
        "SEARCH MODE:",
        search_mode,
    )

    print(
        "COLLECTION COUNT:",
        len(collections),
    )

    print(
        "QUERY VECTOR DIMENSION:",
        len(query_vector),
    )

    print(
        "REPO NAME FILTER:",
        repo_name,
    )

    print(
        "REPO ID FILTER:",
        repo_id,
    )

    print(
        "FILE PATH FILTER:",
        file_path,
    )

    print(
        "LIMIT PER COLLECTION:",
        limit,
    )

    print(
        "===================================\n"
    )

    # ------------------------------------------------------------
    # Build optional payload filters
    # ------------------------------------------------------------

    must_conditions: list[qmodels.Condition] = []

    # Repository name filter
    if repo_name:

        must_conditions.append(
            qmodels.FieldCondition(
                key="repo_name",
                match=qmodels.MatchValue(
                    value=repo_name,
                ),
            )
        )

    # Repository ID filter
    elif repo_id:

        must_conditions.append(
            qmodels.FieldCondition(
                key="repo_id",
                match=qmodels.MatchValue(
                    value=repo_id,
                ),
            )
        )

    # File path filter
    if file_path:

        must_conditions.append(
            qmodels.FieldCondition(
                key="file_path",
                match=qmodels.MatchValue(
                    value=file_path,
                ),
            )
        )

    # ------------------------------------------------------------
    # Create Qdrant filter
    # ------------------------------------------------------------

    query_filter = None

    if must_conditions:

        query_filter = qmodels.Filter(
            must=must_conditions,
        )

    # ------------------------------------------------------------
    # Search every collection
    # ------------------------------------------------------------

    all_points: list[qmodels.ScoredPoint] = []

    for current_collection in collections:

        print(
            "QDRANT SEARCH: Searching collection "
            f"'{current_collection}'..."
        )

        try:

            response = await client.query_points(
                collection_name=current_collection,
                query=query_vector,
                query_filter=query_filter,
                limit=limit,
                score_threshold=score_threshold,
                with_payload=True,
            )

            points = response.points or []

            # ----------------------------------------------------
            # Preserve the collection where each result came from.
            #
            # This is important because results now come from
            # multiple repository-specific collections.
            # ----------------------------------------------------

            for point in points:

                if point.payload is None:
                    point.payload = {}

                point.payload[
                    "_qdrant_collection"
                ] = current_collection

            print(
                "QDRANT SEARCH: "
                f"{len(points)} results from "
                f"'{current_collection}'"
            )

            all_points.extend(points)

        except Exception:

            logger.exception(
                "qdrant_collection_search_failed",
                collection=current_collection,
            )

            print(
                "QDRANT SEARCH: Failed collection "
                f"'{current_collection}', skipping..."
            )

            # ----------------------------------------------------
            # Do not fail the complete search because one
            # collection failed.
            # ----------------------------------------------------

            continue

    # ------------------------------------------------------------
    # No results
    # ------------------------------------------------------------

    if not all_points:

        print(
            "\nQDRANT SEARCH: No results found"
        )

        return []

    # ------------------------------------------------------------
    # Global ranking
    # ------------------------------------------------------------
    #
    # Each collection returns its own top `limit` results.
    #
    # We combine all those results and sort them globally by
    # similarity score.
    # ------------------------------------------------------------

    all_points.sort(
        key=lambda point: float(
            point.score
        ),
        reverse=True,
    )

    # ------------------------------------------------------------
    # Return global top `limit`
    # ------------------------------------------------------------

    final_points = all_points[:limit]

    # ------------------------------------------------------------
    # Debug results
    # ------------------------------------------------------------

    print(
        "\n========== QDRANT SEARCH COMPLETE =========="
    )

    print(
        "TOTAL RAW RESULTS:",
        len(all_points),
    )

    print(
        "FINAL GLOBAL RESULTS:",
        len(final_points),
    )

    for index, point in enumerate(
        final_points[:10],
        start=1,
    ):

        payload = point.payload or {}

        print(
            f"\n--- Global Result {index} ---"
        )

        print(
            "Score:",
            point.score,
        )

        print(
            "Collection:",
            payload.get(
                "_qdrant_collection"
            ),
        )

        print(
            "Repository:",
            payload.get(
                "repo_name"
            ),
        )

        print(
            "File:",
            payload.get(
                "file_path"
            ),
        )

        print(
            "Function:",
            payload.get(
                "function_name"
            ),
        )

        print(
            "Class:",
            payload.get(
                "class_name"
            ),
        )

    print(
        "============================================\n"
    )

    return final_points


# ================================================================
# Delete vectors by file
# ================================================================

async def delete_vectors_by_file(
    collection_name: str,
    repo_id: str,
    file_path: str,
) -> None:
    """
    Delete all vectors associated with a specific file
    in a repository.
    """

    client = get_qdrant_client()

    try:

        await client.delete(
            collection_name=collection_name,
            points_selector=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="repo_id",
                        match=qmodels.MatchValue(
                            value=repo_id,
                        ),
                    ),
                    qmodels.FieldCondition(
                        key="file_path",
                        match=qmodels.MatchValue(
                            value=file_path,
                        ),
                    ),
                ]
            ),
        )

    except Exception:

        logger.exception(
            "qdrant_delete_file_failed",
            collection=collection_name,
            file=file_path,
        )

        raise


# ================================================================
# Delete vectors by repository
# ================================================================

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
                        match=qmodels.MatchValue(
                            value=repo_id,
                        ),
                    ),
                ]
            ),
        )

    except Exception:

        logger.exception(
            "qdrant_delete_repo_failed",
            collection=collection_name,
            repo_id=repo_id,
        )

        raise