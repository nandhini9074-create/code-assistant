"""
app/dependencies.py
FastAPI dependency injection providers for all services.
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.session import get_db
from app.modules.jobs.repository.job_repository import JobRepository
from app.modules.jobs.service.job_service import JobService
from app.modules.repositories.repository.repository_repo import RepositoryRepository
from app.modules.repositories.service.repository_service import RepositoryService
from app.modules.webhooks.validators.webhook_validator import WebhookValidator
from app.modules.webhooks.service.webhook_service import WebhookService
from app.modules.ingestion.repository.ingestion_job_repo import IngestionJobRepository


def get_repository_repo(session: AsyncSession = Depends(get_db)) -> RepositoryRepository:
    return RepositoryRepository(session)


def get_ingestion_job_repo(session: AsyncSession = Depends(get_db)) -> IngestionJobRepository:
    return IngestionJobRepository(session)


def get_webhook_event_repo(session: AsyncSession = Depends(get_db)):
    from app.modules.webhooks.repository.webhook_event_repo import WebhookEventRepository
    return WebhookEventRepository(session)


def get_repository_service(
    repo_repo: RepositoryRepository = Depends(get_repository_repo),
    job_repo: IngestionJobRepository = Depends(get_ingestion_job_repo),
) -> RepositoryService:
    return RepositoryService(repo_repo, job_repo)


def get_job_repository(session: AsyncSession = Depends(get_db)) -> JobRepository:
    return JobRepository(session)


def get_job_service(
    job_repo: JobRepository = Depends(get_job_repository),
) -> JobService:
    return JobService(job_repo)


def get_webhook_validator(
    repo_repo: RepositoryRepository = Depends(get_repository_repo),
) -> WebhookValidator:
    return WebhookValidator(repo_repo)


def get_webhook_service(
    validator: WebhookValidator = Depends(get_webhook_validator),
    job_repo: IngestionJobRepository = Depends(get_ingestion_job_repo),
    event_repo=Depends(get_webhook_event_repo),
) -> WebhookService:
    return WebhookService(validator, job_repo, event_repo)


def get_ingestion_service(
    repo_repo: RepositoryRepository = Depends(get_repository_repo),
    job_repo: IngestionJobRepository = Depends(get_ingestion_job_repo),
    session: AsyncSession = Depends(get_db),
):
    from app.modules.ingestion.repository.file_hash_repo import FileHashRepository
    from app.modules.ingestion.repository.chunk_registry_repo import ChunkRegistryRepository
    from app.modules.ingestion.pipeline.request_validation import RequestValidationStage
    from app.modules.ingestion.pipeline.repository_fetch import RepositoryFetchStage
    from app.modules.ingestion.pipeline.file_filter import FileFilterStage
    from app.modules.ingestion.pipeline.content_fetch import ContentFetchStage
    from app.modules.ingestion.pipeline.file_hash_check import FileHashCheckStage
    from app.modules.ingestion.pipeline.ast_chunking import AstChunkingStage
    from app.modules.ingestion.pipeline.chunk_deduplication import ChunkDeduplicationStage
    from app.modules.ingestion.pipeline.metadata_enrichment import MetadataEnrichmentStage
    from app.modules.ingestion.pipeline.embedding_generation import EmbeddingGenerationStage
    from app.modules.ingestion.pipeline.vector_upsert import VectorUpsertStage
    from app.modules.ingestion.pipeline.deleted_chunk_cleanup import DeletedChunkCleanupStage
    from app.modules.ingestion.pipeline.checkpoint_update import CheckpointUpdateStage
    from app.modules.ingestion.service.ingestion_service import IngestionService

    file_repo = FileHashRepository(session)
    chunk_repo = ChunkRegistryRepository(session)

    return IngestionService(
        RequestValidationStage(repo_repo),
        RepositoryFetchStage(repo_repo),
        FileFilterStage(),
        ContentFetchStage(repo_repo),
        FileHashCheckStage(file_repo),
        AstChunkingStage(),
        ChunkDeduplicationStage(chunk_repo),
        MetadataEnrichmentStage(),
        EmbeddingGenerationStage(),
        VectorUpsertStage(repo_repo, chunk_repo),
        DeletedChunkCleanupStage(repo_repo, file_repo, chunk_repo),
        CheckpointUpdateStage(job_repo),
    )
