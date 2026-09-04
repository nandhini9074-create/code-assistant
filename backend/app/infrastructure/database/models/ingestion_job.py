"""
app/infrastructure/database/models/ingestion_job.py
ORM model for ingestion jobs.
"""

from typing import TYPE_CHECKING
import datetime
import uuid

from sqlalchemy import ForeignKey, Integer, String, Text, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base

if TYPE_CHECKING:
    from app.infrastructure.database.models.repository import Repository


class IngestionJob(Base):
    """
    Represents a single ingestion operation for a repository.
    """

    __tablename__ = "ingestion_jobs"

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

    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    trigger_source: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    
    commit_sha: Mapped[str] = mapped_column(Text, nullable=False)
    previous_commit_sha: Mapped[str | None] = mapped_column(Text, nullable=True)

    files_scanned: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    files_changed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    files_unchanged: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    files_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    
    chunks_upserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunks_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunks_reused: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)

    # Relationships
    repository: Mapped["Repository"] = relationship(  # noqa: F821
        "Repository",
        back_populates="ingestion_jobs",
        lazy="noload",
    )

    @property
    def current_stage(self) -> str:
        return self.status

    @property
    def processed_files_count(self) -> int:
        return self.files_changed + self.files_unchanged

    @property
    def indexed_chunks_count(self) -> int:
        return self.chunks_upserted

    @property
    def updated_at(self) -> datetime.datetime:
        return self.finished_at or self.started_at or self.created_at

    @property
    def completed_at(self) -> datetime.datetime | None:
        return self.finished_at

    @property
    def celery_task_id(self) -> str | None:
        return None

    def __repr__(self) -> str:
        return f"<IngestionJob id={self.id!s} status={self.status!r}>"
