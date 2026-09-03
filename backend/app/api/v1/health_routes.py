"""
app/api/v1/health_routes.py
Health check API routes.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("/")
async def health_check() -> dict:
    """
    Detailed health check endpoint.
    Checks connectivity to PostgreSQL, Qdrant, and Redis.
    """
    checks: dict[str, str] = {}

    # PostgreSQL check
    try:
        from app.infrastructure.database.session import async_session_maker
        async with async_session_maker() as session:
            await session.execute(__import__("sqlalchemy", fromlist=["text"]).text("SELECT 1"))
        checks["postgresql"] = "ok"
    except Exception:
        checks["postgresql"] = "error"

    # Qdrant check
    try:
        from app.infrastructure.qdrant.client import get_qdrant_client
        client = get_qdrant_client()
        await client.get_collections()
        checks["qdrant"] = "ok"
    except Exception:
        checks["qdrant"] = "error"

    # Redis check
    try:
        from app.infrastructure.cache.redis_client import get_redis_client
        redis = await get_redis_client()
        await redis.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "error"

    overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"

    return {"status": overall, "checks": checks}
