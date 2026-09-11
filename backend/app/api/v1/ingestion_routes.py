"""
app/api/v1/ingestion_routes.py
Ingestion API routes.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status, Response

from app.core.enums import TriggerSource, JobStatus
from app.core.exceptions import RepositoryNotFoundError
from app.core.logging import get_logger
from app.dependencies import get_repository_repo, get_ingestion_job_repo
from app.infrastructure.database.models.ingestion_job import IngestionJob
from app.modules.ingestion.repository.ingestion_job_repo import IngestionJobRepository
from app.modules.ingestion.schemas.ingestion_schema import (
    IngestRepositoryRequest,
    IngestionJobResponse,
)
from app.modules.repositories.repository.repository_repo import RepositoryRepository
from app.workers.tasks.ingestion_tasks import ingest_repository_task

logger = get_logger(__name__)
router = APIRouter(prefix="/ingestion", tags=["Ingestion"])


@router.post("/", response_model=IngestionJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_ingestion(
    request: IngestRepositoryRequest,
    repo_repo: RepositoryRepository = Depends(get_repository_repo),
    job_repo: IngestionJobRepository = Depends(get_ingestion_job_repo),
) -> IngestionJobResponse:
    """Trigger a repository ingestion job."""
    logger.info("received_trigger_ingestion_request", repo_id=str(request.repo_id), commit_sha=request.commit_sha)
    repo = await repo_repo.get_by_id(str(request.repo_id))
    if not repo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found.")

    job = IngestionJob(
        repo_id=repo.id,
        job_type="full",
        trigger_source=TriggerSource.GITHUB_URL.value,
        status=JobStatus.QUEUED.value,
        commit_sha=request.commit_sha or "",
    )
    job = await job_repo.create(job)

    ingest_repository_task.delay(
        job_id=str(job.id),
        repo_id=str(repo.id),
        source=TriggerSource.GITHUB_URL.value,
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
    full: bool = False,
    repo_repo: RepositoryRepository = Depends(get_repository_repo),
    job_repo: IngestionJobRepository = Depends(get_ingestion_job_repo),
) -> IngestionJobResponse:
    """Force a reindex of a registered repository."""
    logger.info("received_reindex_repository_request", repo_id=str(repo_id))
    repo = await repo_repo.get_by_id(str(repo_id))
    if not repo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found.",
        )

    # 2. Create an ingestion job
    job = IngestionJob(
        repo_id=repo.id,
        job_type="full" if full else "incremental",
        trigger_source=TriggerSource.GITHUB_URL.value,
        status=JobStatus.QUEUED.value,
        commit_sha="",
    )

    job = await job_repo.create(job)

    # 3. Queue the existing ingestion task
    ingest_repository_task.delay(
        job_id=str(job.id),
        repo_id=str(repo.id),
        source=TriggerSource.GITHUB_URL.value,
        full_reindex=full,
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


@router.delete("/{repo_id}/index", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_index(
    repo_id: uuid.UUID,
    repo_repo: RepositoryRepository = Depends(get_repository_repo),
) -> Response:
    """Wipe the Qdrant collection and chunk registry rows without deregistering the repo."""
    repo = await repo_repo.get_by_id(str(repo_id))
    if not repo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found.")
        
    try:
        from app.infrastructure.qdrant.client import get_qdrant_client
        client = get_qdrant_client()
        await client.delete_collection(repo.qdrant_collection_name)
    except Exception as e:
        logger.warning("failed_to_drop_qdrant_collection", repo_id=str(repo_id), error=str(e))

    # Wipe chunk registry rows (cascade not triggered since repo isn't deleted)
    from app.infrastructure.database.session import get_session_factory
    from sqlalchemy import delete
    from app.infrastructure.database.models.chunk_registry import ChunkRegistry
    from app.infrastructure.database.models.file_hash import FileHash
    
    session_factory = get_session_factory()
    async with session_factory() as session:
        await session.execute(delete(ChunkRegistry).where(ChunkRegistry.repo_id == repo.id))
        await session.execute(delete(FileHash).where(FileHash.repo_id == repo.id))
        await session.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
