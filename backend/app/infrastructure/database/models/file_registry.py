"""
app/infrastructure/database/models/file_registry.py
ORM model for the file hash registry.

Tracks the SHA-256 hash of every indexed file, enabling file-level
change detection without re-fetching unchanged content.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import FileStatus
from app.infrastructure.database.base import Base, TimestampMixin


class FileRegistry(Base, TimestampMixin):
    """
    Records the state of each file that has been seen by the ingestion pipeline.

    **Key design decisions:**

    - ``file_hash`` is the SHA-256 of the actual file content (not the Git blob SHA).
      This is the application's change detection signal (see Section 10 of the spec).
    - ``blob_sha`` is the Git tree blob SHA, stored as metadata only.
    - When ``status=DELETED``, the file no longer exists in the repository HEAD.
      Its associated Qdrant vectors must be cleaned up by the pipeline.
    """

    __tablename__ = "file_registry"

    # Primary Key

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique record identifier.",
    )

    # Foreign Key

    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Repository this file belongs to.",
    )

    # File Identity

    file_path: Mapped[str] = mapped_column(
        String(2048),
        nullable=False,
        doc="Relative file path within the repository (e.g. 'src/service/user.py').",
    )

    language: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        doc="Detected programming language (e.g. 'python', 'typescript').",
    )

    # Hashes

    file_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        doc=(
            "SHA-256 hex digest of the canonical file content. "
            "Used as the application-level change detection signal. "
            "NULL before first successful ingestion."
        ),
    )

    blob_sha: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
        doc=(
            "Git blob SHA from the repository tree (stored as metadata only). "
            "NOT used for application-level change detection."
        ),
    )

    commit_sha: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
        doc="Git commit SHA at which this file was last processed.",
    )

    # Status

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=FileStatus.ACTIVE.value,
        doc="ACTIVE = file exists in HEAD; DELETED = file was removed.",
    )

    # Size

    file_size_bytes: Mapped[int | None] = mapped_column(
        nullable=True,
        doc="File size in bytes at last ingestion (for diagnostics).",
    )

    # Relationship

    repository: Mapped["Repository"] = relationship(  # noqa: F821
        "Repository",
        back_populates="file_records",
        lazy="noload",
    )

    # Constraints & Indexes

    __table_args__ = (
        # A (repo, path) pair must be unique — one record per file per repo
        UniqueConstraint("repository_id", "file_path", name="uq_file_registry_repo_path"),
        Index("ix_file_registry_repo_id", "repository_id"),
        Index("ix_file_registry_status", "status"),
        Index("ix_file_registry_file_hash", "file_hash"),
        Index("ix_file_registry_repo_path", "repository_id", "file_path"),
    )

    def __repr__(self) -> str:
        return (
            f"<FileRegistry id={self.id!s} path={self.file_path!r} "
            f"hash={self.file_hash!r:.8} status={self.status!r}>"
        )
