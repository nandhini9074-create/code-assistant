"""
app/infrastructure/database/session.py
Async SQLAlchemy engine and session factory for Code Explorer.

Provides:
  - async_engine: the SQLAlchemy async engine (singleton)
  - AsyncSessionLocal: session factory
  - get_db(): FastAPI dependency that yields a managed async session
  - init_db() / close_db(): lifecycle hooks called from app/main.py
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.exceptions import DatabaseError
from app.core.logging import get_logger

logger = get_logger(__name__)

# Module-level singletons (initialized by init_db)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


# Engine / Session Initialization

def _build_engine(database_url: str, pool_size: int, max_overflow: int, echo: bool) -> AsyncEngine:
    """Create and return the async SQLAlchemy engine."""
    return create_async_engine(
        database_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        echo=echo,
        pool_pre_ping=True,         # validates connections before use
        pool_recycle=3600,          # recycle connections after 1 hour
        connect_args={
            "statement_cache_size": 0,  # recommended for asyncpg + pgbouncer
        },
    )


async def init_db() -> None:
    """
    Initialize the database engine and session factory.

    Call once during application startup (app/main.py lifespan).
    Safe to call multiple times — will not re-create if already initialized.
    """
    global _engine, _session_factory

    if _engine is not None:
        return  # already initialized

    from app.config import get_settings  # local import avoids circular dep at module load

    settings = get_settings()

    logger.info("database_init", url=settings.database_url.split("@")[-1])  # log only host/dbname

    _engine = _build_engine(
        database_url=settings.database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        echo=settings.database_echo_sql,
    )

    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,     # avoid lazy-load issues after commit
        autoflush=False,
        autocommit=False,
    )

    logger.info("database_ready")


async def close_db() -> None:
    """
    Dispose the engine and release all database connections.

    Call during application shutdown (app/main.py lifespan).
    """
    global _engine, _session_factory

    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("database_closed")


def get_engine() -> AsyncEngine:
    """Return the active async engine. Raises if not initialized."""
    if _engine is None:
        raise DatabaseError(
            "Database engine is not initialized. Call init_db() first.",
            code="DB_NOT_INITIALIZED",
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the active session factory. Raises if not initialized."""
    if _session_factory is None:
        raise DatabaseError(
            "Session factory is not initialized. Call init_db() first.",
            code="DB_NOT_INITIALIZED",
        )
    return _session_factory


# FastAPI Dependency

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields a managed async database session.

    Automatically commits on success and rolls back on exception.

    Usage::

        @router.get("/example")
        async def example(db: AsyncSession = Depends(get_db)):
            ...
    """
    factory = get_session_factory()

    async with factory() as session:
        try:
            yield session
            await session.commit()
        except SQLAlchemyError as exc:
            await session.rollback()
            logger.error("database_session_error", exc_info=exc)
            raise DatabaseError(
                f"Database operation failed: {exc}",
                code="DB_OPERATION_FAILED",
            ) from exc
        except Exception:
            await session.rollback()
            raise


# Health Check Helper

async def check_db_health() -> dict[str, Any]:
    """
    Perform a lightweight connectivity check against PostgreSQL.

    Returns a dict with ``status`` and ``latency_ms``.
    Used by the health endpoint.
    """
    import time

    from sqlalchemy import text

    try:
        factory = get_session_factory()
        start = time.perf_counter()
        async with factory() as session:
            await session.execute(text("SELECT 1"))
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        return {"status": "healthy", "latency_ms": latency_ms}
    except Exception as exc:
        return {"status": "unhealthy", "error": str(exc)}
