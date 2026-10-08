"""
app/infrastructure/database/models/webhook_event.py
ORM model for GitHub webhook deliveries.
"""

from typing import TYPE_CHECKING
import datetime
import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import DateTime

from app.infrastructure.database.base import Base

if TYPE_CHECKING:
    from app.infrastructure.database.models.repository import Repository


class WebhookEvent(Base):
    """
    Represents a raw webhook payload received from GitHub.
    """

    __tablename__ = "webhook_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    repo_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repos.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    delivery_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    event_type: Mapped[str] = mapped_column(String(255), nullable=False)
    signature_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    payload_raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    processed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    
    ingestion_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ingestion_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )

    received_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.datetime.now(datetime.timezone.utc), 
        nullable=False
    )

    # Relationships
    repository: Mapped["Repository"] = relationship(  # noqa: F821
        "Repository",
        back_populates="webhook_events",
        lazy="noload",
    )

    def __repr__(self) -> str:
        return f"<WebhookEvent id={self.id!s} type={self.event_type!r}>"
