"""
app/infrastructure/database/models/chunk_registry.py
ORM model for the chunk-level deduplication registry.

Tracks every indexed code chunk by its SHA-256 hash so that unchanged chunks
can reuse their existing Qdrant vector without re-embedding.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base, TimestampMixin


class ChunkRegistry(Base, TimestampMixin):
    """
    Records each indexed code chunk and its corresponding Qdrant point ID.

    **Deduplication flow:**

    1. Compute ``chunk_hash = SHA-256(normalized chunk content)``.
    2. Look up ``chunk_hash`` in this table.
    3. If found → reuse ``point_id`` (skip embedding generation).
    4. If not found → generate embedding, upsert to Qdrant, insert here.

    A ``point_id`` is a deterministic UUID derived from
    ``(repo_id, file_path, chunk_hash)`` so re-ingestion is idempotent.
    """

    __tablename__ = "chunk_registry"

    # Primary Key

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique chunk record identifier.",
    )

    # Foreign Key

    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Repository this chunk belongs to.",
    )

    # File Location

    file_path: Mapped[str] = mapped_column(
        String(2048),
        nullable=False,
        doc="Relative file path within the repository.",
    )

    # Chunk Identity

    chunk_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc=(
            "SHA-256 hex digest of the normalized chunk content. "
            "Used for chunk-level deduplication."
        ),
    )

    point_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        doc=(
            "Deterministic UUID used as the Qdrant point ID. "
            "Derived from (repo_id, file_path, chunk_hash) using uuid5."
        ),
    )

    # Chunk Position

    start_line: Mapped[int | None] = mapped_column(
        nullable=True,
        doc="Line number where this chunk starts (1-indexed).",
    )

    end_line: Mapped[int | None] = mapped_column(
        nullable=True,
        doc="Line number where this chunk ends (inclusive).",
    )

    # Chunk Type & Symbol

    chunk_type: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        doc="Chunk type: function | method | class | interface | module | other.",
    )

    function_name: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
        doc="Function or method name if chunk_type is function/method.",
    )

    class_name: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
        doc="Class name if chunk is a class or a method within a class.",
    )

    language: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        doc="Programming language of this chunk.",
    )

    # Commit Reference

    commit_sha: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
        doc="Commit SHA at which this chunk was last indexed.",
    )

    file_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        doc="file_hash of the parent file at the time this chunk was indexed.",
    )

    # Extended Metadata

    metadata_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        doc=(
            "Full chunk metadata payload stored as JSON for debugging and "
            "response generation (mirrors the Qdrant payload). "
            "Includes: imports, docstring, raw_code snippet header."
        ),
    )

    # Relationship

    repository: Mapped["Repository"] = relationship(  # noqa: F821
        "Repository",
        back_populates="chunk_records",
        lazy="noload",
    )

    # Constraints & Indexes

    __table_args__ = (
        # A chunk_hash must be unique within a repository
        UniqueConstraint(
            "repository_id", "chunk_hash",
            name="uq_chunk_registry_repo_chunk_hash",
        ),
        Index("ix_chunk_registry_repo_id", "repository_id"),
        Index("ix_chunk_registry_chunk_hash", "chunk_hash"),
        Index("ix_chunk_registry_point_id", "point_id"),
        Index("ix_chunk_registry_repo_file", "repository_id", "file_path"),
        Index("ix_chunk_registry_function", "function_name"),
    )

    def __repr__(self) -> str:
        return (
            f"<ChunkRegistry id={self.id!s} file={self.file_path!r} "
            f"chunk_type={self.chunk_type!r} hash={self.chunk_hash[:8]!r}>"
        )
