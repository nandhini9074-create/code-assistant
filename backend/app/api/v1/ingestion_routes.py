"""
app/api/v1/ingestion_routes.py
Ingestion API routes.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import IngestionSource, JobStatus
from app.core.exceptions import RepositoryNotFoundError
from app.dependencies import get_repository_repo, get_ingestion_job_repo
from app.infrastructure.database.models.ingestion_job import IngestionJob
from app.infrastructure.database.session import get_db
from app.modules.ingestion.repository.ingestion_job_repo import IngestionJobRepository
from app.modules.ingestion.schemas.ingestion_schema import IngestRepositoryRequest, IngestionJobResponse
from app.modules.repositories.repository.repository_repo import RepositoryRepository
from app.workers.tasks.ingestion_tasks import ingest_repository_task

router = APIRouter(prefix="/ingestion", tags=["Ingestion"])


@router.post("/", response_model=IngestionJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_ingestion(
    request: IngestRepositoryRequest,
    repo_repo: RepositoryRepository = Depends(get_repository_repo),
    job_repo: IngestionJobRepository = Depends(get_ingestion_job_repo),
) -> IngestionJobResponse:
    """Trigger a repository ingestion job."""
    repo = await repo_repo.get_by_id(str(request.repo_id))
    if not repo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found.")

    job = IngestionJob(
        repository_id=repo.id,
        source=IngestionSource.GITHUB_URL.value,
        status=JobStatus.PENDING.value,
        commit_sha=request.commit_sha,
    )
    job = await job_repo.create(job)

    # Enqueue Celery task
    ingest_repository_task.delay(
        job_id=str(job.id),
        repo_id=str(repo.id),
        source=IngestionSource.GITHUB_URL.value,
        commit_sha=request.commit_sha,
    )

    return IngestionJobResponse(
        job_id=str(job.id),
        repo_id=str(repo.id),
        status=job.status,
        message="Ingestion job queued.",
    )


@router.post("/{repo_id}/reindex", response_model=IngestionJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def reindex_repository(
    repo_id: uuid.UUID,
    repo_repo: RepositoryRepository = Depends(get_repository_repo),
    job_repo: IngestionJobRepository = Depends(get_ingestion_job_repo),
) -> IngestionJobResponse:
    """Force a full reindex of a registered repository."""
    repo = await repo_repo.get_by_id(str(repo_id))
    if not repo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found.")

    job = IngestionJob(
        repository_id=repo.id,
        source=IngestionSource.GITHUB_URL.value,
        status=JobStatus.PENDING.value,
    )
    job = await job_repo.create(job)

    ingest_repository_task.delay(
        job_id=str(job.id),
        repo_id=str(repo.id),
        source=IngestionSource.GITHUB_URL.value,
    )

    return IngestionJobResponse(
        job_id=str(job.id),
        repo_id=str(repo.id),
        status=job.status,
        message="Reindex job queued.",
    )
