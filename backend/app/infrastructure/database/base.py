"""
app/infrastructure/database/base.py
SQLAlchemy declarative base and shared mixins for Code Explorer.

All ORM models must inherit from Base.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedColumn, mapped_column


# Declarative Base

class Base(DeclarativeBase):
    """
    Shared SQLAlchemy declarative base for all Code Explorer ORM models.

    Every model that inherits from this class is automatically registered
    with Alembic's autogenerate mechanism (via ``migrations/env.py``).
    """

    # Allow subclasses to set __tablename__ automatically if omitted
    # (not enforced here; all models define it explicitly)


# Shared Mixins

class TimestampMixin:
    """
    Adds ``created_at`` and ``updated_at`` columns to any model.

    Both columns are stored as UTC timestamps.
    ``updated_at`` is automatically refreshed on every UPDATE by the database
    server (via ``onupdate``).
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=False,
        doc="UTC timestamp when this record was first created.",
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        index=False,
        doc="UTC timestamp when this record was last updated.",
    )
