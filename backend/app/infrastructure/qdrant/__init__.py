"""
app/infrastructure/qdrant/__init__.py
Qdrant infrastructure module.
"""

from app.infrastructure.qdrant.client import (
    close_qdrant,
    get_qdrant_client,
    init_qdrant,
)
from app.infrastructure.qdrant.collection_manager import ensure_collection_exists
from app.infrastructure.qdrant.vector_repository import (
    delete_vectors_by_file,
    delete_vectors_by_repo,
    generate_point_id,
    search_vectors,
    upsert_vectors,
)

__all__ = [
    "init_qdrant",
    "close_qdrant",
    "get_qdrant_client",
    "ensure_collection_exists",
    "generate_point_id",
    "upsert_vectors",
    "search_vectors",
    "delete_vectors_by_file",
    "delete_vectors_by_repo",
]
