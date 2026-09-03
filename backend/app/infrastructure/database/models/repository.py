"""
app/infrastructure/database/models/repository.py
ORM model for registered GitHub repositories.

PostgreSQL source of truth for repository identity, status, and indexing state.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import RepositoryStatus
from app.infrastructure.database.base import Base, TimestampMixin


class Repository(Base, TimestampMixin):
    """
    Represents a registered code repository.

    A repository must be registered before ingestion can be triggered.
    Tracks the current indexing state, last-known commit SHA, and Qdrant
    collection assignment.
    """

    __tablename__ = "repositories"

    # Primary Key

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique repository identifier (UUIDv4).",
    )

    # Identity

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Repository name (e.g. 'my-service').",
    )

    full_name: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        unique=True,
        doc="Full qualified name: owner/repo (e.g. 'acme/my-service').",
    )

    github_url: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        unique=True,
        doc="Canonical GitHub HTTPS URL (e.g. https://github.com/acme/my-service).",
    )

    owner: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="GitHub repository owner (user or organization).",
    )

    # Branch & Commit

    default_branch: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="main",
        doc="The primary branch being indexed (e.g. 'main', 'master').",
    )

    current_commit_sha: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
        doc="SHA of the most recently indexed commit. NULL until first ingestion.",
    )

    # Qdrant

    qdrant_collection: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="code_chunks",
        doc="Qdrant collection name where this repository's vectors are stored.",
    )

    # Status

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=RepositoryStatus.PENDING.value,
        doc="Current lifecycle state: PENDING | INDEXING | INDEXED | FAILED | STALE.",
    )

    # Optional Metadata

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Optional repository description (from GitHub or user input).",
    )

    github_repo_id: Mapped[int | None] = mapped_column(
        nullable=True,
        doc="Numeric GitHub repository ID (from GitHub API response).",
    )

    github_token: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Optional per-repository GitHub PAT to override the global token.",
    )

    # Relationships

    ingestion_jobs: Mapped[list["IngestionJob"]] = relationship(  # noqa: F821
        "IngestionJob",
        back_populates="repository",
        cascade="all, delete-orphan",
        lazy="noload",
    )

    file_records: Mapped[list["FileRegistry"]] = relationship(  # noqa: F821
        "FileRegistry",
        back_populates="repository",
        cascade="all, delete-orphan",
        lazy="noload",
    )

    chunk_records: Mapped[list["ChunkRegistry"]] = relationship(  # noqa: F821
        "ChunkRegistry",
        back_populates="repository",
        cascade="all, delete-orphan",
        lazy="noload",
    )

    webhook_events: Mapped[list["WebhookEvent"]] = relationship(  # noqa: F821
        "WebhookEvent",
        back_populates="repository",
        cascade="all, delete-orphan",
        lazy="noload",
    )

    # Indexes

    __table_args__ = (
        Index("ix_repositories_owner", "owner"),
        Index("ix_repositories_status", "status"),
        Index("ix_repositories_full_name", "full_name"),
    )

    def __repr__(self) -> str:
        return f"<Repository id={self.id!s} full_name={self.full_name!r} status={self.status!r}>"
