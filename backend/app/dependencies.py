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


def get_repository_service(
    repo_repo: RepositoryRepository = Depends(get_repository_repo),
) -> RepositoryService:
    return RepositoryService(repo_repo)


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
) -> WebhookService:
    return WebhookService(validator, job_repo)
