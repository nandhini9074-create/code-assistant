"""
app/infrastructure/database/models/ingestion_job.py
ORM model for ingestion jobs.

Tracks every ingestion operation (GitHub URL, ZIP upload, webhook trigger, reindex).
Supports checkpointing so failed jobs can be resumed rather than restarted.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import IngestionSource, JobStage, JobStatus
from app.infrastructure.database.base import Base, TimestampMixin


class IngestionJob(Base, TimestampMixin):
    """
    Represents a single ingestion operation for a repository.

    Jobs are created synchronously by the API and processed asynchronously
    by Celery workers.  The ``checkpoint_data`` JSON column stores pipeline
    progress so a failed job can be resumed.
    """

    __tablename__ = "ingestion_jobs"

    # Primary Key

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique job identifier (UUIDv4).",
    )

    # Foreign Key

    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Repository this job belongs to.",
    )

    # Source & Status

    source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        doc="Ingestion trigger: GITHUB_URL | ZIP_UPLOAD | WEBHOOK | REINDEX.",
    )

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=JobStatus.QUEUED.value,
        doc="Current job lifecycle state: QUEUED | RUNNING | COMPLETED | FAILED | CANCELLED.",
    )

    stage: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default=JobStage.INITIALIZING.value,
        doc="Current pipeline stage for progress reporting.",
    )

    # Commit

    commit_sha: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
        doc="Git commit SHA this ingestion is processing.",
    )

    target_branch: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Branch being ingested (NULL = repository default branch).",
    )

    # Progress Counters

    total_files: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Total number of files discovered in the repository tree.",
    )

    processed_files: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Number of files fully processed by the pipeline.",
    )

    skipped_files: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Number of files skipped (unchanged hash or filtered).",
    )

    deleted_files: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Number of files detected as deleted from the repository.",
    )

    total_chunks: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Total number of chunks produced by AST chunking.",
    )

    processed_chunks: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Number of chunks that had embeddings generated.",
    )

    reused_chunks: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Number of chunks that reused existing vectors (unchanged chunk hash).",
    )

    # Error & Checkpoint

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Human-readable error message if status=FAILED.",
    )

    error_traceback: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Internal traceback stored server-side (never exposed to clients).",
    )

    checkpoint_data: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        doc=(
            "Serialized pipeline checkpoint. Stores the list of already-processed "
            "file paths, last successful stage, and any per-stage state needed for "
            "resuming a failed job without restarting from zero."
        ),
    )

    # Celery

    celery_task_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Celery task ID for this job (useful for task introspection).",
    )

    # Relationship

    repository: Mapped["Repository"] = relationship(  # noqa: F821
        "Repository",
        back_populates="ingestion_jobs",
        lazy="noload",
    )

    # Indexes

    __table_args__ = (
        Index("ix_ingestion_jobs_status", "status"),
        Index("ix_ingestion_jobs_repo_status", "repository_id", "status"),
        Index("ix_ingestion_jobs_celery_task", "celery_task_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<IngestionJob id={self.id!s} repo={self.repository_id!s} "
            f"status={self.status!r} stage={self.stage!r}>"
        )
