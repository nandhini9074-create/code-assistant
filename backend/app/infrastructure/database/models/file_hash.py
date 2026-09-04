"""
app/infrastructure/database/models/file_hash.py
ORM model for file hashes.
"""

from typing import TYPE_CHECKING
import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.infrastructure.database.models.repository import Repository


class FileHash(Base, TimestampMixin):
    """
    Represents a file hash entry in a repository.
    """

    __tablename__ = "file_hashes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    blob_sha: Mapped[str] = mapped_column(Text, nullable=False)
    file_hash: Mapped[str] = mapped_column(Text, nullable=False)
    last_commit_sha: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)

    last_seen_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ingestion_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    repository: Mapped["Repository"] = relationship(  # noqa: F821
        "Repository",
        back_populates="file_hashes",
        lazy="noload",
    )

    def __repr__(self) -> str:
        return f"<FileHash id={self.id!s} path={self.file_path!r}>"
