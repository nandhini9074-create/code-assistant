"""
app/infrastructure/database/models/chunk_registry.py
ORM model for code chunks.
"""

from typing import TYPE_CHECKING
import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.infrastructure.database.models.repository import Repository


class ChunkRegistry(Base, TimestampMixin):
    """
    Represents a code chunk entry in a repository.
    """

    __tablename__ = "chunk_registry"

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
    chunk_hash: Mapped[str] = mapped_column(Text, nullable=False)
    symbol_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    symbol_type: Mapped[str] = mapped_column(String(50), nullable=False)
    
    start_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    embedding_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    qdrant_point_id: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)

    last_seen_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ingestion_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    repository: Mapped["Repository"] = relationship(  # noqa: F821
        "Repository",
        back_populates="chunk_records",
        lazy="noload",
    )

    @property
    def point_id(self) -> str | None:
        return self.qdrant_point_id

    def __repr__(self) -> str:
        return f"<ChunkRegistry id={self.id!s} hash={self.chunk_hash!r}>"
