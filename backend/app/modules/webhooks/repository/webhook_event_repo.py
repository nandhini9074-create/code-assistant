"""
app/modules/webhooks/repository/webhook_event_repo.py
Repository pattern for WebhookEvent model.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models.webhook_event import WebhookEvent


class WebhookEventRepository:
    """Database repository for WebhookEvent entity."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, event: WebhookEvent) -> WebhookEvent:
        """Create a new webhook event record."""
        self.session.add(event)
        await self.session.commit()
        await self.session.refresh(event)
        return event

    async def get_by_delivery_id(self, delivery_id: str) -> WebhookEvent | None:
        """Get webhook event by GitHub delivery ID."""
        stmt = select(WebhookEvent).where(WebhookEvent.delivery_id == delivery_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, event_id: uuid.UUID | str) -> WebhookEvent | None:
        """Get webhook event by internal UUID."""
        uid = uuid.UUID(event_id) if isinstance(event_id, str) else event_id
        return await self.session.get(WebhookEvent, uid)

    async def exists(self, delivery_id: str) -> bool:
        """Check if a webhook event with the given delivery ID already exists."""
        stmt = select(WebhookEvent.id).where(WebhookEvent.delivery_id == delivery_id)
        result = await self.session.execute(stmt)
        return result.first() is not None

    async def mark_processed_by_job_id(self, job_id: uuid.UUID | str) -> None:
        """Mark all webhook events associated with an ingestion job as processed."""
        uid = uuid.UUID(job_id) if isinstance(job_id, str) else job_id
        stmt = select(WebhookEvent).where(WebhookEvent.ingestion_job_id == uid)
        result = await self.session.execute(stmt)
        events = result.scalars().all()
        for event in events:
            event.processed = True
        await self.session.commit()
