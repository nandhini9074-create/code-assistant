"""
app/infrastructure/database/models/webhook_event.py
ORM model for GitHub webhook event records.

Used to enforce idempotency: each GitHub webhook delivery (identified by
X-GitHub-Delivery) is recorded here so duplicate deliveries are silently skipped.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import WebhookEventStatus, WebhookEventType
from app.infrastructure.database.base import Base, TimestampMixin


class WebhookEvent(Base, TimestampMixin):
    """
    Records a received GitHub webhook delivery.

    **Idempotency guarantee:**
    The ``delivery_id`` column is unique. Before processing any webhook,
    the service checks for an existing record with the same delivery_id.
    If found, the event is skipped immediately without re-processing.

    The associated ingestion job (if any) is referenced by ``ingestion_job_id``.
    """

    __tablename__ = "webhook_events"

    # Primary Key

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique event record identifier.",
    )

    # GitHub Delivery Identity

    delivery_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        doc=(
            "Value of the X-GitHub-Delivery header. "
            "Used as the idempotency key — must be unique across all deliveries."
        ),
    )

    # Event Type & Status

    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default=WebhookEventType.PUSH.value,
        doc="GitHub event type (X-GitHub-Event header): push | ping | unknown.",
    )

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=WebhookEventStatus.RECEIVED.value,
        doc="Processing status: RECEIVED | PROCESSED | SKIPPED | FAILED.",
    )

    # Repository

    repository_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc=(
            "Repository associated with this event. "
            "NULL if the repository is not registered or could not be identified."
        ),
    )

    # Payload Metadata

    payload_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        doc="SHA-256 of the raw webhook payload body (for auditing).",
    )

    ref: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Git ref from the push event (e.g. 'refs/heads/main').",
    )

    head_commit_sha: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
        doc="SHA of the head commit in the push event.",
    )

    pusher: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="GitHub username of the pusher.",
    )

    # File Change Summary

    added_files_count: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        doc="Number of files added in this push event.",
    )

    modified_files_count: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        doc="Number of files modified in this push event.",
    )

    removed_files_count: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        doc="Number of files removed in this push event.",
    )

    # Linked Job

    ingestion_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ingestion_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Ingestion job triggered by this webhook event (if any).",
    )

    # Error

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Error message if processing failed.",
    )

    # Relationships

    repository: Mapped["Repository"] = relationship(  # noqa: F821
        "Repository",
        back_populates="webhook_events",
        lazy="noload",
    )

    # Indexes

    __table_args__ = (
        # delivery_id is already UNIQUE but we add a named index for clarity
        UniqueConstraint("delivery_id", name="uq_webhook_events_delivery_id"),
        Index("ix_webhook_events_status", "status"),
        Index("ix_webhook_events_repo_id", "repository_id"),
        Index("ix_webhook_events_event_type", "event_type"),
    )

    def __repr__(self) -> str:
        return (
            f"<WebhookEvent id={self.id!s} delivery={self.delivery_id!r} "
            f"type={self.event_type!r} status={self.status!r}>"
        )
