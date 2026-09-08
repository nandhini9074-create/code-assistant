"""
app/api/v1/ingestion_routes.py
Ingestion API routes.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.enums import IngestionSource, JobStatus
from app.dependencies import get_repository_repo, get_ingestion_job_repo
from app.infrastructure.database.models.ingestion_job import IngestionJob
from app.modules.ingestion.repository.ingestion_job_repo import IngestionJobRepository
from app.modules.ingestion.schemas.ingestion_schema import IngestionJobResponse
from app.modules.repositories.repository.repository_repo import RepositoryRepository
from app.workers.tasks.ingestion_tasks import ingest_repository_task


router = APIRouter(prefix="/ingestion", tags=["Ingestion"])


@router.post(
    "/{repo_id}/reindex",
    response_model=IngestionJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def reindex_repository(
    repo_id: uuid.UUID,
    repo_repo: RepositoryRepository = Depends(get_repository_repo),
    job_repo: IngestionJobRepository = Depends(get_ingestion_job_repo),
) -> IngestionJobResponse:
    """
    Trigger a full ingestion/reindex for a registered repository.

    The ingestion itself is executed asynchronously by the Celery worker.
    """

    # 1. Check that the repository exists
    repo = await repo_repo.get_by_name(repo_name)

    if not repo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found.",
        )

    # 2. Create an ingestion job
    job = IngestionJob(
        repository_id=repo.id,
        source=IngestionSource.GITHUB_URL.value,
        status=JobStatus.QUEUED.value,
    )

    job = await job_repo.create(job)

    # 3. Queue the existing ingestion task
    ingest_repository_task.delay(
        job_id=str(job.id),
        repo_id=str(repo.id),
        source=IngestionSource.GITHUB_URL.value,
    )

    # 4. Return the response expected by IngestionJobResponse
    return IngestionJobResponse(
        job_id=str(job.id),
        repo_id=str(repo.id),
        status=job.status,
        stage="QUEUED",
        processed_files=0,
        processed_chunks=0,
        error_info=None,
    )