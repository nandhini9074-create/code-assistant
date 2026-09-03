"""
app/modules/embedding/service/__init__.py
Embedding service module.
"""

from app.modules.embedding.service.embedding_service import (
    generate_embeddings,
    get_embedding_provider,
)

__all__ = [
    "get_embedding_provider",
    "generate_embeddings",
]
