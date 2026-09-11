"""
app/workers/tasks/ingestion_tasks.py
Celery tasks for code repository ingestion.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.enums import TriggerSource
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
from app.modules.ingestion.repository.file_hash_repo import FileHashRepository
from app.modules.ingestion.repository.ingestion_job_repo import IngestionJobRepository
from app.modules.ingestion.service.ingestion_service import IngestionService
from app.modules.repositories.repository.repository_repo import RepositoryRepository
from app.modules.webhooks.repository.webhook_event_repo import WebhookEventRepository
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


async def _run_ingestion(job_id: str, repo_id: str, source: str, commit_sha: str | None, full_reindex: bool = False, webhook_diff: dict[str, list[str]] | None = None) -> dict[str, Any]:
    from app.config import get_settings
    from app.infrastructure.database.session import _build_engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    settings = get_settings()
    # Create task-scoped engine to prevent asyncpg connection pool sharing across event loops
    engine = _build_engine(
        database_url=settings.database_url,
        pool_size=5,
        max_overflow=10,
        echo=settings.database_echo_sql,
    )
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    
    try:
        async with session_factory() as session:
            repo_repo = RepositoryRepository(session)
            job_repo = IngestionJobRepository(session)
            file_repo = FileHashRepository(session)
            chunk_repo = ChunkRegistryRepository(session)
            event_repo = WebhookEventRepository(session)
            
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
            checkpoint_stage = CheckpointUpdateStage(job_repo, event_repo)
            
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
            
            ingestion_source = TriggerSource(source)
            
            # Fetch the repo to get the per-repository token if it exists
            repo = await repo_repo.get_by_id(repo_id)
            github_token = repo.access_token_ref if repo else None
            
            result = await service.run_pipeline(
                job_id=job_id,
                repo_id=repo_id,
                repo_name=repo.repo_name if repo else "unknown",
                source=ingestion_source,
                commit_sha=commit_sha or "",
                github_token=github_token,
                full_reindex=full_reindex,
                webhook_diff=webhook_diff,
            )
            
            return {
                "status": "success" if result.success else "failed",
                "job_id": result.job_id,
                "processed_files": result.processed_files_count,
                "processed_file_paths": result.processed_file_paths,
                "chunks_indexed": result.indexed_chunks_count,
                "chunk_ids": result.chunk_ids,
                "error": result.error_message,
            }
    finally:
        await engine.dispose()


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
    full_reindex: bool = False,
    webhook_diff: dict[str, list[str]] | None = None,
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
        # Check if an event loop is already running (e.g. Celery eager mode inside FastAPI process)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    asyncio.run,
                    _run_ingestion(job_id, repo_id, source, commit_sha, full_reindex, webhook_diff),
                )
                return future.result()
        else:
            return asyncio.run(_run_ingestion(job_id, repo_id, source, commit_sha, full_reindex, webhook_diff))
    except Exception as exc:
        logger.error("ingestion_task_failed", job_id=job_id, exc_info=exc)
        raise self.retry(exc=exc)

