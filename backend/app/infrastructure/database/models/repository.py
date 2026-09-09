"""
app/infrastructure/database/models/repository.py
ORM model for registered GitHub repositories.

PostgreSQL source of truth for repository identity, status, and indexing state.
"""

from typing import TYPE_CHECKING
import uuid

from sqlalchemy import Boolean, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.infrastructure.database.models.chunk_registry import ChunkRegistry
    from app.infrastructure.database.models.file_hash import FileHash
    from app.infrastructure.database.models.ingestion_job import IngestionJob
    from app.infrastructure.database.models.webhook_event import WebhookEvent


class Repository(Base, TimestampMixin):
    """
    Represents a registered code repository.
    """

    __tablename__ = "repos"

    # Primary Key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    repo_url: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    repo_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(255), nullable=False, default="main")
    is_private: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    access_token_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    qdrant_collection_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_indexed_commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # Relationships
    ingestion_jobs: Mapped[list["IngestionJob"]] = relationship(  # noqa: F821
        "IngestionJob",
        back_populates="repository",
        cascade="all, delete-orphan",
        lazy="noload",
    )

    file_hashes: Mapped[list["FileHash"]] = relationship(  # noqa: F821
        "FileHash",
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

    @property
    def name(self) -> str:
        return self.repo_name

    @property
    def owner(self) -> str:
        # Extract owner from URL or default
        parts = self.repo_url.rstrip("/").split("/")
        return parts[-2] if len(parts) >= 2 else "local"

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo_name}"

    @property
    def github_url(self) -> str:
        return self.repo_url

    @property
    def qdrant_collection(self) -> str:
        return self.qdrant_collection_name.lower().replace("/", "_").replace("-", "_").replace(".", "_").replace(":", "_")

    @property
    def current_commit_sha(self) -> str | None:
        return self.last_indexed_commit_sha

    @property
    def status(self) -> str:
        return "active" if self.last_indexed_commit_sha else "pending"

    def __repr__(self) -> str:
        return f"<Repository id={self.id!s} name={self.repo_name!r}>"
