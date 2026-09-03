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
