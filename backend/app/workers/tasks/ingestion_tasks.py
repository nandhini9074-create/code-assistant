"""
app/workers/tasks/ingestion_tasks.py
Celery tasks for code repository ingestion.
"""

from __future__ import annotations

import asyncio
from typing import Any

from asgiref.sync import async_to_sync

from app.core.enums import IngestionSource
from app.core.logging import get_logger
from app.infrastructure.database.session import get_db
from app.infrastructure.github.blobs_client import fetch_blob_content
from app.infrastructure.github.trees_client import fetch_repository_tree
from app.modules.ingestion.pipeline import (
    AstChunkingStage,
    CheckpointUpdateStage,
    ChunkDeduplicationStage,
    ContentFetchStage,
    DeletedChunkCleanupStage,
    EmbeddingGenerationStage,
    FileFilterStage,
    FileHashCheckStage,
    MetadataEnrichmentStage,
    RepositoryFetchStage,
    RequestValidationStage,
    VectorUpsertStage,
)
from app.modules.ingestion.repository.chunk_registry_repo import ChunkRegistryRepository
from app.modules.ingestion.repository.file_registry_repo import FileRegistryRepository
from app.modules.ingestion.repository.ingestion_job_repo import IngestionJobRepository
from app.modules.ingestion.service.ingestion_service import IngestionService
from app.modules.repositories.repository.repository_repo import RepositoryRepository
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


async def _run_ingestion(job_id: str, repo_id: str, source: str, commit_sha: str | None) -> dict[str, Any]:
    # Set up dependencies manually since we are outside FastAPI request context
    # In a real application, you'd use a DI container or proper factory function
    from app.infrastructure.database.session import async_session_maker
    
    async with async_session_maker() as session:
        repo_repo = RepositoryRepository(session)
        job_repo = IngestionJobRepository(session)
        file_repo = FileRegistryRepository(session)
        chunk_repo = ChunkRegistryRepository(session)
        
        # Instantiate stages
        val_stage = RequestValidationStage(repo_repo)
        repo_fetch_stage = RepositoryFetchStage(repo_repo)
        file_filter_stage = FileFilterStage()
        content_fetch_stage = ContentFetchStage(repo_repo)
        hash_check_stage = FileHashCheckStage(file_repo)
        ast_stage = AstChunkingStage()
        dedup_stage = ChunkDeduplicationStage(chunk_repo)
        meta_stage = MetadataEnrichmentStage()
        embed_stage = EmbeddingGenerationStage()
        upsert_stage = VectorUpsertStage(repo_repo, chunk_repo)
        cleanup_stage = DeletedChunkCleanupStage(repo_repo, file_repo, chunk_repo)
        checkpoint_stage = CheckpointUpdateStage(job_repo)
        
        service = IngestionService(
            val_stage,
            repo_fetch_stage,
            file_filter_stage,
            content_fetch_stage,
            hash_check_stage,
            ast_stage,
            dedup_stage,
            meta_stage,
            embed_stage,
            upsert_stage,
            cleanup_stage,
            checkpoint_stage,
        )
        
        ingestion_source = IngestionSource(source)
        result = await service.run_pipeline(
            job_id=job_id,
            repo_id=repo_id,
            source=ingestion_source,
            commit_sha=commit_sha or "",
        )
        
        return {
            "status": "success" if result.success else "failed",
            "job_id": result.job_id,
            "processed_files": result.processed_files_count,
            "chunks_indexed": result.indexed_chunks_count,
            "error": result.error_message,
        }


@celery_app.task(
    bind=True,
    name="tasks.ingest_repository",
    queue="ingestion",
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
    reject_on_worker_lost=True,
)
def ingest_repository_task(
    self: Any,
    job_id: str,
    repo_id: str,
    source: str,
    commit_sha: str | None = None,
) -> dict[str, Any]:
    """
    Background task to ingest a GitHub repository.
    """
    logger.info(
        "starting_ingestion_task",
        job_id=job_id,
        repo_id=repo_id,
        source=source,
        commit_sha=commit_sha,
    )
    
    try:
        # Execute the async ingestion flow in an event loop using `async_to_sync`
        # In a real environment, you'd want to handle the event loop carefully
        # if Celery worker is running in a threading/gevent model.
        return async_to_sync(_run_ingestion)(job_id, repo_id, source, commit_sha)
    except Exception as exc:
        logger.error("ingestion_task_failed", job_id=job_id, exc_info=exc)
        raise self.retry(exc=exc)

