"""
app/modules/jobs/service/job_service.py
Service for the jobs module.
"""

from app.core.enums import JobStatus
from app.core.exceptions import JobNotFoundError
from app.modules.jobs.repository.job_repository import JobRepository
from app.modules.jobs.schemas.job_schema import JobStatusResponse


class JobService:
    """Service for querying job status."""
    
    def __init__(self, job_repo: JobRepository) -> None:
        self.job_repo = job_repo

    async def get_job_status(self, job_id: str) -> JobStatusResponse:
        """Get the status of a specific job."""
        job = await self.job_repo.get_job(job_id)
        if not job:
            raise JobNotFoundError(job_id)
            
        return JobStatusResponse(
            id=str(job.id),
            status=JobStatus(job.status),
            stage=job.current_stage,
            processed_files_count=job.processed_files_count,
            indexed_chunks_count=job.indexed_chunks_count,
            error_message=job.error_message,
            created_at=job.created_at,
            updated_at=job.updated_at,
            completed_at=job.completed_at,
        )
        
    async def list_jobs_for_repo(self, repo_id: str, limit: int = 50, offset: int = 0) -> list[JobStatusResponse]:
        """List all jobs for a repository."""
        jobs = await self.job_repo.list_jobs_for_repo(repo_id, limit, offset)
        
        return [
            JobStatusResponse(
                id=str(job.id),
                status=JobStatus(job.status),
                stage=job.current_stage,
                processed_files_count=job.processed_files_count,
                indexed_chunks_count=job.indexed_chunks_count,
                error_message=job.error_message,
                created_at=job.created_at,
                updated_at=job.updated_at,
                completed_at=job.completed_at,
            )
            for job in jobs
        ]

    async def cancel_job(self, job_id: str) -> None:
        """Cancel an in-flight job."""
        from app.core.enums import JobStatus
        
        job = await self.job_repo.get_job(job_id)
        if not job:
            raise JobNotFoundError(job_id)
            
        if job.status not in (JobStatus.QUEUED.value, JobStatus.RUNNING.value):
            return
            
        # Revoke the celery task
        if job.celery_task_id:
            try:
                from app.workers.celery_app import celery_app
                celery_app.control.revoke(job.celery_task_id, terminate=True)
            except Exception as e:
                from app.core.logging import get_logger
                logger = get_logger(__name__)
                logger.error(f"Failed to revoke celery task for job {job_id}: {e}")
                
        # Update status
        await self.job_repo.update_status(job_id, JobStatus.CANCELLED.value)
