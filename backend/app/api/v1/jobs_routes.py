"""
app/api/v1/jobs_routes.py
Job status API routes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.exceptions import JobNotFoundError
from app.core.logging import get_logger
from app.dependencies import get_job_service
from app.modules.jobs.schemas.job_schema import JobStatusResponse
from app.modules.jobs.service.job_service import JobService

logger = get_logger(__name__)
router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    service: JobService = Depends(get_job_service),
) -> JobStatusResponse:
    """Get the current status and progress of an ingestion job."""
    logger.info("fetching_job_status", job_id=job_id)
    try:
        return await service.get_job_status(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/repository/{repo_id}", response_model=list[JobStatusResponse])
async def list_jobs_for_repo(
    repo_id: str,
    limit: int = 50,
    offset: int = 0,
    service: JobService = Depends(get_job_service),
) -> list[JobStatusResponse]:
    """Get job history for a repository."""
    return await service.list_jobs_for_repo(repo_id, limit, offset)


@router.get("/{job_id}/logs")
async def get_job_logs(
    job_id: str,
    service: JobService = Depends(get_job_service),
) -> dict:
    """Get logs for a specific job."""
    try:
        job = await service.get_job_status(job_id)
        # Placeholder for structured logs. Currently returning the main error message if present.
        return {
            "job_id": job_id,
            "error_message": job.error_message,
            "logs": []  # Requires a JobLog database model to store per-file logs
        }
    except JobNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/{job_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_job(
    job_id: str,
    service: JobService = Depends(get_job_service),
) -> dict:
    """Cancel an in-flight job."""
    try:
        await service.cancel_job(job_id)
        return {"message": "Job cancellation requested."}
    except JobNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
