"""
app/modules/embedding/service/embedding_service.py
Service for interacting with the Embedding layer.
"""

from __future__ import annotations

from app.modules.embedding.providers.voyage_provider import VoyageProvider

# Singleton provider instance
_provider: VoyageProvider | None = None


def get_embedding_provider() -> VoyageProvider:
    """
    Get the configured embedding provider (defaults to Voyage AI).
    """
    global _provider
    if _provider is None:
        _provider = VoyageProvider()
    return _provider


async def generate_embeddings(
    texts: list[str],
    input_type: str = "document",
) -> list[list[float]]:
    """
    Generate embeddings for a list of strings.
    
    Args:
        texts: The texts to embed.
        input_type: "document" for chunk indexing, "query" for search queries.
        
    Returns:
        List of embedding vectors.
    """
    provider = get_embedding_provider()
    return await provider.generate_embeddings(texts=texts, input_type=input_type)
