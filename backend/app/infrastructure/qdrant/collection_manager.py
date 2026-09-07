"""
app/infrastructure/qdrant/collection_manager.py
Manages Qdrant collections and payload indices for Code Explorer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from qdrant_client.http import models as qmodels

from app.core.logging import get_logger
from app.infrastructure.qdrant.client import get_qdrant_client

if TYPE_CHECKING:
    from qdrant_client import AsyncQdrantClient

logger = get_logger(__name__)


async def ensure_collection_exists(
    collection_name: str,
    vector_size: int = 1024,
) -> None:
    """
    Ensure a Qdrant collection exists and has the required payload indices.
    If it doesn't exist, it creates it.
    """
    client = get_qdrant_client()

    try:
        collections_response = await client.get_collections()
        existing_collections = {c.name for c in collections_response.collections}

        if collection_name in existing_collections:
            logger.debug("qdrant_collection_exists", collection=collection_name)
            # Verify collection config matches expected vector size (1024) and cosine distance
            coll_info = await client.get_collection(collection_name=collection_name)
            vectors_config = coll_info.config.params.vectors
            if isinstance(vectors_config, qmodels.VectorParams):
                if vectors_config.size != vector_size:
                    raise ValueError(
                        f"Qdrant collection {collection_name} dimension mismatch: "
                        f"expected {vector_size}, found {vectors_config.size}"
                    )
                if vectors_config.distance != qmodels.Distance.COSINE:
                    raise ValueError(
                        f"Qdrant collection {collection_name} distance mismatch: "
                        f"expected Cosine, found {vectors_config.distance}"
                    )
            return

        logger.info("qdrant_creating_collection", collection=collection_name)
        await client.create_collection(
            collection_name=collection_name,
            vectors_config=qmodels.VectorParams(
                size=vector_size,
                distance=qmodels.Distance.COSINE,
            ),
        )

        # Create payload indices for faster filtering
        await _create_indices(client, collection_name)

        logger.info("qdrant_collection_created", collection=collection_name)

    except Exception as exc:
        logger.error("qdrant_collection_error", collection=collection_name, exc_info=exc)
        raise


async def _create_indices(client: "AsyncQdrantClient", collection_name: str) -> None:
    """Create payload indices for filtering."""
    # Index repo_id for filtering vectors by repository
    await client.create_payload_index(
        collection_name=collection_name,
        field_name="repo_id",
        field_schema=qmodels.PayloadSchemaType.KEYWORD,
    )
    
    # Index file_path for potential path-based scoping
    await client.create_payload_index(
        collection_name=collection_name,
        field_name="file_path",
        field_schema=qmodels.PayloadSchemaType.KEYWORD,
    )
