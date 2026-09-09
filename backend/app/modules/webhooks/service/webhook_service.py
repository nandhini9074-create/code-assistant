"""
app/modules/webhooks/service/webhook_service.py
Service for processing GitHub webhooks.
"""

from typing import Any

from app.core.enums import TriggerSource, JobStatus
from app.core.exceptions import DuplicateWebhookDeliveryError, ValidationError
from app.core.logging import get_logger
from app.infrastructure.database.models.ingestion_job import IngestionJob
from app.infrastructure.database.models.webhook_event import WebhookEvent
from app.modules.ingestion.repository.ingestion_job_repo import IngestionJobRepository
from app.modules.webhooks.schemas.webhook_schema import WebhookEventResponse
from app.modules.webhooks.validators.webhook_validator import WebhookValidator
from app.workers.tasks.ingestion_tasks import ingest_repository_task

logger = get_logger(__name__)


from app.modules.webhooks.repository.webhook_event_repo import WebhookEventRepository

class WebhookService:
    def __init__(
        self,
        validator: WebhookValidator,
        job_repo: IngestionJobRepository,
        event_repo: WebhookEventRepository,
    ) -> None:
        self.validator = validator
        self.job_repo = job_repo
        self.event_repo = event_repo

    async def handle_event(self, event_type: str, delivery_id: str, payload: dict[str, Any]) -> WebhookEventResponse:
        """Process a GitHub webhook event."""
        if await self.event_repo.exists(delivery_id):
            logger.info("webhook_ignored", reason="Duplicate delivery", delivery_id=delivery_id)
            return WebhookEventResponse(status="ignored", message="Duplicate delivery")

        if event_type == "ping":
            return await self._handle_ping(delivery_id, payload)
        elif event_type == "push":
            return await self._handle_push(delivery_id, payload)
        else:
            return WebhookEventResponse(status="ignored", message=f"Unsupported event: {event_type}")

    async def _handle_ping(self, delivery_id: str, payload: dict[str, Any]) -> WebhookEventResponse:
        """Handle a GitHub ping event."""
        repository = payload.get("repository", {})
        repo_name = repository.get("full_name", "unknown")
        
        logger.info("webhook_ping_received", repo=repo_name, delivery_id=delivery_id)
        
        webhook_event = WebhookEvent(
            delivery_id=delivery_id,
            event_type="ping",
            signature_valid=True,
            payload_raw=payload,
            processed=True,
        )
        await self.event_repo.create(webhook_event)
        
        return WebhookEventResponse(status="ok", message="pong")

    async def _handle_push(self, delivery_id: str, payload: dict[str, Any]) -> WebhookEventResponse:
        """Process a GitHub push event."""
        # 2 & 3. Validate repository and branch
        try:
            validation_result = await self.validator.validate_push_event("push", payload)
        except ValidationError as exc:
            logger.info("webhook_ignored", reason=str(exc))
            return WebhookEventResponse(status="ignored", message=str(exc))
            
        repo = validation_result["repo"]
        
        # 4. Extract specific commit if possible
        head_commit = payload.get("head_commit", {})
        commit_sha = head_commit.get("id")
        if not commit_sha:
            return WebhookEventResponse(status="ignored", message="No head_commit found")

        # 5. Extract file diff from commits
        webhook_diff: dict[str, list[str]] = {"added": [], "modified": [], "deleted": []}
        for commit in payload.get("commits", []):
            webhook_diff["added"].extend(commit.get("added", []))
            webhook_diff["modified"].extend(commit.get("modified", []))
            webhook_diff["deleted"].extend(commit.get("removed", []))
            
        webhook_diff["added"] = list(set(webhook_diff["added"]))
        webhook_diff["modified"] = list(set(webhook_diff["modified"]))
        webhook_diff["deleted"] = list(set(webhook_diff["deleted"]))

        # 6. Create ingestion job
        job = IngestionJob(
            repo_id=repo.id,
            job_type="incremental",
            trigger_source=TriggerSource.WEBHOOK.value,
            status=JobStatus.QUEUED.value,
            commit_sha=commit_sha,
        )
        job = await self.job_repo.create(job)
        
        # 7. Submit Celery task
        ingest_repository_task.delay(
            job_id=str(job.id),
            repo_id=str(repo.id),
            source=TriggerSource.WEBHOOK.value,
            commit_sha=commit_sha,
            webhook_diff=webhook_diff,
        )
        
        # 8. Store webhook event record
        webhook_event = WebhookEvent(
            delivery_id=delivery_id,
            event_type="push",
            repo_id=repo.id,
            signature_valid=True,
            payload_raw=payload,
            processed=False,
            ingestion_job_id=job.id,
        )
        await self.event_repo.create(webhook_event)
        
        # 9. Return immediately
        return WebhookEventResponse(
            status="accepted",
            message="Push event accepted for processing",
            job_id=str(job.id),
        )
