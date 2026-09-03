"""
app/api/v1/ingestion.py
API endpoints for triggering ingestion jobs.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import IngestionSource, JobStatus
from app.infrastructure.database.models.ingestion_job import IngestionJob
from app.infrastructure.database.models.repository import Repository
from app.infrastructure.database.session import get_db

router = APIRouter(prefix="/ingestion", tags=["Ingestion"])


@router.post("/trigger/{repo_id}", status_code=202)
async def trigger_ingestion(
    repo_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Trigger a full repository ingestion job.
    Returns the job ID for tracking.
    """
    repo = await db.get(Repository, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found.")
        
    job = IngestionJob(
        repository_id=repo.id,
        source=IngestionSource.GITHUB_URL.value,
        status=JobStatus.QUEUED.value,
    )
    
    db.add(job)
    await db.commit()
    await db.refresh(job)
    
    # In a fully integrated system, we would dispatch the Celery task here:
    # from app.workers.tasks.ingestion_tasks import process_ingestion_job
    # task = process_ingestion_job.delay(str(job.id))
    # 
    # For now we'll just return the job info.
    
    return {
        "job_id": str(job.id),
        "repository_id": str(repo.id),
        "status": job.status,
        "message": "Ingestion job queued.",
    }


@router.get("/jobs/{job_id}")
async def get_job_status(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Get the status and progress of an ingestion job.
    """
    job = await db.get(IngestionJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
        
    return {
        "id": str(job.id),
        "status": job.status,
        "stage": job.stage,
        "progress": {
            "total_files": job.total_files,
            "processed_files": job.processed_files,
            "skipped_files": job.skipped_files,
            "total_chunks": job.total_chunks,
        },
        "error_message": job.error_message,
    }
