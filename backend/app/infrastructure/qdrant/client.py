"""
app/infrastructure/qdrant/client.py
Async Qdrant client lifecycle management for Code Explorer.
"""
from __future__ import annotations
from qdrant_client import AsyncQdrantClient
from app.core.exceptions import QdrantError
from app.core.logging import get_logger
logger = get_logger(__name__)
# Module-level singleton
_qdrant_client: AsyncQdrantClient | None = None
async def init_qdrant() -> None:
    """
    Initialize the global Qdrant client.
    Call once at application startup.
    """
    global _qdrant_client

    if _qdrant_client is not None:
        return

    from app.config import get_settings
    settings = get_settings()

    logger.info("qdrant_init", url=settings.qdrant_url)

    try:
        _qdrant_client = AsyncQdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            timeout=settings.qdrant_timeout,
        )
        
        # Verify connection
        await _qdrant_client.get_collections()
        logger.info("qdrant_ready")
    except Exception as exc:
        _qdrant_client = None
        logger.error("qdrant_init_error", exc_info=exc)
        raise QdrantError(f"Failed to connect to Qdrant: {exc}") from exc
async def close_qdrant() -> None:
    """
    Close the Qdrant client connection.
    Call at application shutdown.
    """
    global _qdrant_client

    if _qdrant_client is not None:
        await _qdrant_client.close()
        _qdrant_client = None
        logger.info("qdrant_closed")
def get_qdrant_client() -> AsyncQdrantClient:
    """
    Get the global Qdrant client instance.
    Raises QdrantError if not initialized.
    """
    if _qdrant_client is None:
        raise QdrantError("Qdrant client not initialized. Call init_qdrant() first.")
    return _qdrant_client
