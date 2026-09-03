"""
app/modules/ingestion/pipeline/checkpoint_update.py
Pipeline stage: Checkpoint update.
"""

from app.core.enums import JobStatus
from app.modules.ingestion.domain.ingestion_domain import IngestionContext
from app.modules.ingestion.repository.ingestion_job_repo import IngestionJobRepository


class CheckpointUpdateStage:
    def __init__(self, job_repo: IngestionJobRepository) -> None:
        self.job_repo = job_repo

    async def execute(self, context: IngestionContext) -> None:
        """Updates job progress in database."""
        # Calculate progress
        processed_files = len(context.files)
        processed_chunks = sum(len(f.chunks) for f in context.files)
        
        await self.job_repo.update_progress(
            context.job_id,
            processed_files=processed_files,
            processed_chunks=processed_chunks,
        )
        
        await self.job_repo.update_status(
            context.job_id,
            status=JobStatus.RUNNING,
            stage="pipeline_complete",
        )
