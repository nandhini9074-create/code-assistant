"""
app/infrastructure/cache/redis_client.py
Async Redis client for caching, rate limiting, and idempotency keys.
"""

from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis

from app.config import get_settings
from app.core.exceptions import RedisError
from app.core.logging import get_logger

logger = get_logger(__name__)

# Module-level singleton
_redis_client: Redis | None = None


async def init_redis() -> None:
    """
    Initialize the global async Redis client.
    Call once at application startup.
    If Redis is unreachable, logs a warning and allows the app to start without cache.
    """
    global _redis_client
    if _redis_client is not None:
        return

    settings = get_settings()
    logger.info("redis_init", url=settings.redis_url.split("@")[-1])  # mask passwords if any

    try:
        client = Redis.from_url(
            settings.redis_url,
            decode_responses=True,  # Return strings instead of bytes
            socket_connect_timeout=2.0,
        )
        # Ping to verify connection
        await client.ping()
        _redis_client = client
        logger.info("redis_ready")
    except Exception as exc:
        _redis_client = None
        logger.warning(
            "redis_unavailable_continuing_without_cache",
            error=str(exc),
            hint="Running in no-cache mode. Start Redis to enable caching and distributed locks.",
        )


async def close_redis() -> None:
    """
    Close the global Redis client.
    Call on application shutdown.
    """
    global _redis_client
    if _redis_client is not None:
        try:
            await _redis_client.close()
        except Exception:
            pass
        _redis_client = None
        logger.info("redis_closed")


def get_redis_client() -> Redis | None:
    """
    Get the initialized global Redis client (None if Redis is unavailable).
    """
    return _redis_client


# Common Helpers

async def set_cache(key: str, value: Any, ttl_seconds: int | None = None) -> None:
    """
    Set a value in the cache, optionally serialized as JSON.
    """
    client = get_redis_client()
    if client is None:
        return
    
    if not isinstance(value, str):
        value = json.dumps(value)
        
    try:
        if ttl_seconds:
            await client.setex(key, ttl_seconds, value)
        else:
            await client.set(key, value)
    except Exception as exc:
        logger.warning("redis_set_failed", key=key, exc_info=exc)


async def get_cache(key: str, as_json: bool = False) -> Any | None:
    """
    Get a value from the cache.
    """
    client = get_redis_client()
    if client is None:
        return None
    try:
        value = await client.get(key)
        if value and as_json:
            return json.loads(value)
        return value
    except Exception as exc:
        logger.warning("redis_get_failed", key=key, exc_info=exc)
        return None


async def acquire_lock(key: str, ttl_seconds: int = 60) -> bool:
    """
    Attempt to acquire a distributed lock.
    Returns True if acquired (or if Redis is unavailable in local dev), False otherwise.
    Used for webhook idempotency and race condition prevention.
    """
    client = get_redis_client()
    if client is None:
        # In local dev without Redis, allow operation to proceed
        return True
    try:
        # SETNX equivalent (set if not exists)
        acquired = await client.set(key, "1", ex=ttl_seconds, nx=True)
        return bool(acquired)
    except Exception as exc:
        logger.error("redis_lock_failed", key=key, exc_info=exc)
        return True


async def release_lock(key: str) -> None:
    """
    Release a distributed lock.
    """
    client = get_redis_client()
    if client is None:
        return
    try:
        await client.delete(key)
    except Exception as exc:
        logger.error("redis_release_failed", key=key, exc_info=exc)
