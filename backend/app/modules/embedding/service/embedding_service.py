"""
app/modules/embedding/service/embedding_service.py

Service for interacting with the Embedding layer.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.modules.embedding.providers.jina_provider import JinaProvider

logger = get_logger(__name__)

# Singleton provider instance
_provider: JinaProvider | None = None


def get_embedding_provider() -> JinaProvider:
    """
    Get the configured embedding provider (defaults to Jina AI).
    """
    global _provider

    if _provider is None:
        _provider = JinaProvider()
    return _provider


async def generate_embeddings(
    texts: list[str],
    input_type: str = "document",
) -> list[list[float]]:
    """
    Generate embeddings for a list of strings using Jina AI.

    Args:
        texts: The texts to embed.
        input_type: "document" for chunk indexing (retrieval.passage),
                    "query" for search queries (retrieval.query).

    Returns:
        List of 1024-dimensional embedding vectors.
    """
    if not texts:
        logger.debug("generate_embeddings_called_with_empty_list")
        return []

    logger.info("generating_embeddings_started", count=len(texts), input_type=input_type)
    provider = get_embedding_provider()
    embeddings = await provider.generate_embeddings(texts=texts, input_type=input_type)
    logger.info("generating_embeddings_completed", count=len(embeddings))
    return embeddings
