"""
migrations/env.py
Alembic environment configuration for Code Explorer.

Supports both:
  - Offline mode: generates SQL without a live database connection.
  - Online mode:  runs migrations against a live async PostgreSQL connection.

Database URL is read from the DATABASE_URL environment variable (via app config),
NOT from alembic.ini — so no credentials are stored in version control.
"""

from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

# Ensure the backend package is on sys.path
# Needed when alembic is run from the backend/ directory
_backend_root = Path(__file__).resolve().parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Import all models so their tables register with Base.metadata
# This import MUST come before `target_metadata` is set
from app.infrastructure.database.base import Base
import app.infrastructure.database.models  # noqa: F401  — registers all models

# Alembic Config Object
config = context.config

# Set up Python logging from alembic.ini [loggers] section
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target Metadata
target_metadata = Base.metadata

# Override sqlalchemy.url with DATABASE_URL env var
def _get_database_url() -> str:
    """
    Read the database URL from the application config (env var).
    Falls back to alembic.ini value only if the env var is unset.
    """
    try:
        from app.config import get_settings
        return get_settings().database_url
    except Exception:
        # Fallback: use value from alembic.ini
        url = config.get_main_option("sqlalchemy.url")
        if not url:
            raise RuntimeError(
                "DATABASE_URL environment variable is not set and "
                "sqlalchemy.url is not configured in alembic.ini."
            )
        return url


# Offline Mode

def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    Generates SQL scripts without a database connection.
    Useful for reviewing migrations before applying them.
    """
    url = _get_database_url()

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# Online Mode

def do_run_migrations(connection: Connection) -> None:
    """Run migrations against an active database connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """
    Run migrations in 'online' mode using an async engine.

    asyncpg requires an async engine; we synchronize via ``run_sync``.
    """
    url = _get_database_url()

    # Build a temporary async engine for migrations
    # (We do NOT reuse the application engine here)
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = url

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # No connection pooling during migrations
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online migrations."""
    asyncio.run(run_async_migrations())


# Entry Point

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
