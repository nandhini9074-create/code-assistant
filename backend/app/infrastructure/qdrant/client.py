"""
app/infrastructure/qdrant/client.py
Async Qdrant client lifecycle management for Code Explorer.
"""
from __future__ import annotations

import asyncio
from qdrant_client import AsyncQdrantClient


from app.core.exceptions import QdrantError
from app.core.logging import get_logger
logger = get_logger(__name__)
# Module-level singleton
_qdrant_client: AsyncQdrantClient | None = None
_qdrant_loop: asyncio.AbstractEventLoop | None = None


async def init_qdrant() -> None:
    """
    Initialize the global Qdrant client.
    Call once at application startup.
    """
    global _qdrant_client, _qdrant_loop

    if _qdrant_client is not None:
        return

    from app.config import get_settings
    settings = get_settings()

    logger.info("qdrant_init", url=settings.qdrant_url)

    client = AsyncQdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        timeout=int(settings.qdrant_timeout),
    )
    
    # Verify connection with retries for temporary DNS/network glitches
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            await client.get_collections()
            _qdrant_client = client
            try:
                _qdrant_loop = asyncio.get_running_loop()
            except RuntimeError:
                _qdrant_loop = None
            logger.info("qdrant_ready")
            return
        except Exception as exc:
            logger.warning(
                "qdrant_init_attempt_failed",
                attempt=attempt,
                max_attempts=max_attempts,
                error=str(exc),
            )
            if attempt == max_attempts:
                _qdrant_client = None
                _qdrant_loop = None
                logger.error("qdrant_init_error", exc_info=exc)
            await asyncio.sleep(1.5)


async def close_qdrant() -> None:
    """
    Close the Qdrant client connection.
    Call at application shutdown.
    """
    global _qdrant_client, _qdrant_loop

    if _qdrant_client is not None:
        try:
            await _qdrant_client.close()
        except Exception:
            pass
        _qdrant_client = None
        _qdrant_loop = None
        logger.info("qdrant_closed")
def get_qdrant_client() -> AsyncQdrantClient:
    """
    Get the global Qdrant client instance, ensuring it is bound to the active event loop.
    Raises QdrantError if not initialized.
    """
    global _qdrant_client, _qdrant_loop

    if _qdrant_client is None:
        raise QdrantError("Qdrant client not initialized. Call init_qdrant() first.")

    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None


    if _qdrant_loop is not None and current_loop is not None and _qdrant_loop != current_loop:
        from app.config import get_settings
        settings = get_settings()
        _qdrant_client = AsyncQdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            timeout=int(settings.qdrant_timeout),
        )
        _qdrant_loop = current_loop

    return _qdrant_client

