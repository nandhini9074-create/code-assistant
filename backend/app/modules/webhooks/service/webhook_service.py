"""
app/modules/webhooks/service/webhook_service.py
Service for processing GitHub webhooks.
"""

from typing import Any

from app.core.enums import IngestionSource, JobStatus
from app.core.exceptions import DuplicateWebhookDeliveryError, ValidationError
from app.core.logging import get_logger
from app.infrastructure.database.models.ingestion_job import IngestionJob
from app.infrastructure.database.models.webhook_event import WebhookEvent
from app.modules.ingestion.repository.ingestion_job_repo import IngestionJobRepository
from app.modules.webhooks.schemas.webhook_schema import WebhookEventResponse
from app.modules.webhooks.validators.webhook_validator import WebhookValidator
from app.workers.tasks.ingestion_tasks import ingest_repository_task

logger = get_logger(__name__)


class WebhookService:
    def __init__(
        self,
        validator: WebhookValidator,
        job_repo: IngestionJobRepository,
        # In a real app we'd have a WebhookEventRepository here
    ) -> None:
        self.validator = validator
        self.job_repo = job_repo

    async def process_push_event(self, event_type: str, delivery_id: str, payload: dict[str, Any]) -> WebhookEventResponse:
        """Process a GitHub push event."""
        # 1. Check idempotency (mocked here, should use a WebhookEvent repo)
        # if await self.webhook_event_repo.exists(delivery_id):
        #     raise DuplicateWebhookDeliveryError(delivery_id)
            
        # 2 & 3. Validate repository and branch
        try:
            validation_result = await self.validator.validate_push_event(event_type, payload)
        except ValidationError as exc:
            logger.info("webhook_ignored", reason=str(exc))
            return WebhookEventResponse(status="ignored", message=str(exc))
            
        repo = validation_result["repo"]
        
        # 4. Extract specific commit if possible (simplification: we just ingest the whole head commit)
        head_commit = payload.get("head_commit", {})
        commit_sha = head_commit.get("id")
        if not commit_sha:
            return WebhookEventResponse(status="ignored", message="No head_commit found")

        # 5. Create ingestion job
        job = IngestionJob(
            repo_id=repo.id,
            source=IngestionSource.WEBHOOK,
            status=JobStatus.PENDING,
            commit_sha=commit_sha,
        )
        job = await self.job_repo.create(job)
        
        # 6. Submit Celery task
        # Using string representation of UUID for Celery
        ingest_repository_task.delay(
            job_id=str(job.id),
            repo_id=str(repo.id),
            source=IngestionSource.WEBHOOK.value,
            commit_sha=commit_sha,
        )
        
        # 7. Store webhook event record
        webhook_event = WebhookEvent(
            delivery_id=delivery_id,
            event_type=event_type,
            repository_id=repo.id,
            payload_json=payload,
        )
        # await self.webhook_event_repo.create(webhook_event)
        
        # 8. Return immediately
        return WebhookEventResponse(
            status="accepted",
            message="Push event accepted for processing",
            job_id=str(job.id),
        )
