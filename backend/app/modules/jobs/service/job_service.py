"""
app/modules/jobs/service/job_service.py
Service for the jobs module.
"""

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
            status=job.status,
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
                status=job.status,
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
