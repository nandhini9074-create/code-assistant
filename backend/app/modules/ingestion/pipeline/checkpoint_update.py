"""
app/modules/ingestion/pipeline/checkpoint_update.py
Pipeline stage: Checkpoint update.
"""

from app.core.enums import JobStatus
from app.core.logging import get_logger
from app.modules.ingestion.domain.ingestion_domain import IngestionContext
from app.modules.ingestion.repository.ingestion_job_repo import IngestionJobRepository
from app.modules.webhooks.repository.webhook_event_repo import WebhookEventRepository

logger = get_logger(__name__)


class CheckpointUpdateStage:
    def __init__(
        self,
        job_repo: IngestionJobRepository,
        event_repo: WebhookEventRepository | None = None,
    ) -> None:
        self.job_repo = job_repo
        self.event_repo = event_repo

    async def execute(self, context: IngestionContext) -> None:
        """Updates job progress in database."""
        logger.info("stage_12_checkpoint_update_started", job_id=context.job_id)
        # Calculate progress
        failed_files_count = len(context.failed_files)
        successful_files_count = sum(1 for f in context.files if f.fetch_status == "success" or f.fetch_status.value == "success") if context.files else 0
        processed_chunks = sum(len(f.chunks) for f in context.files)
        
        # Determine status: if any files failed to fetch, mark as PARTIAL if some succeeded, or COMPLETED
        final_status = JobStatus.PARTIAL if failed_files_count > 0 and successful_files_count > 0 else (
            JobStatus.FAILED if failed_files_count > 0 and successful_files_count == 0 else JobStatus.COMPLETED
        )
        
        await self.job_repo.update_progress(
            context.job_id,
            processed_files=successful_files_count,
            processed_chunks=processed_chunks,
        )
        
        await self.job_repo.update_status(
            context.job_id,
            status=final_status,
            stage="pipeline_complete",
        )

        if self.event_repo is not None and context.job_id:
            try:
                await self.event_repo.mark_processed_by_job_id(context.job_id)
            except Exception as exc:
                logger.warning("failed_to_mark_webhook_event_processed", job_id=context.job_id, error=str(exc))
        logger.info(
            "stage_12_checkpoint_update_completed",
            job_id=context.job_id,
            processed_files=successful_files_count,
            failed_files=failed_files_count,
            processed_chunks=processed_chunks,
            status=final_status.value if hasattr(final_status, "value") else str(final_status),
        )
