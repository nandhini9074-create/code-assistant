"""
app/modules/embedding/service/embedding_service.py

Service for interacting with the Embedding layer.
"""

from __future__ import annotations

from app.modules.embedding.providers.jina_provider import JinaProvider


_provider: JinaProvider | None = None


def get_embedding_provider() -> JinaProvider:
    """Get the configured Jina embedding provider."""

    global _provider

    if _provider is None:
        _provider = JinaProvider()

    return _provider


async def generate_embeddings(
    texts: list[str],
    input_type: str = "document",
) -> list[list[float]]:
    """Generate embeddings for a list of strings."""

    provider = get_embedding_provider()

    return await provider.generate_embeddings(
        texts=texts,
        input_type=input_type,
    )