"""
app/modules/repositories/service/repository_service.py
Service for repository business logic.
"""

from __future__ import annotations

from typing import Sequence

import uuid

from app.core.enums import RepositoryStatus
from app.core.exceptions import RepositoryAlreadyExistsError, RepositoryNotFoundError
from app.core.logging import get_logger
from app.infrastructure.database.models.repository import Repository
from app.modules.repositories.repository.repository_repo import RepositoryRepository
from app.modules.repositories.schemas.repository_schema import CreateRepositoryRequest, UpdateRepositoryRequest
from app.modules.repositories.validators.github_url_validator import validate_and_parse_github_url
from app.shared.types.repo_types import RepoId

logger = get_logger(__name__)


class RepositoryService:
    """Service layer for managing repositories."""
    
    def __init__(
        self,
        repo: RepositoryRepository,
        job_repo: IngestionJobRepository | None = None,
    ) -> None:
        self.repo = repo
        self.job_repo = job_repo

    async def register_repository(self, request: CreateRepositoryRequest) -> Repository:
        """
        Validate URL, check for duplicates, register a new repository, and auto-trigger initial indexing.
        """
        logger.info("repository_registration_started", url=request.repo_url, branch=request.branch)
        try:
            owner, name = validate_and_parse_github_url(request.repo_url)
        except Exception as exc:
            logger.error("repository_url_validation_failed", url=request.repo_url, error=str(exc))
            raise

        full_name = f"{owner}/{name}"
        logger.info("repository_url_validated", owner=owner, repo_name=name, full_name=full_name)
        
        existing = await self.repo.get_by_url(request.repo_url) or await self.repo.get_by_full_name(full_name)
        if existing:
            logger.warning("repository_registration_duplicate", full_name=full_name, repo_id=str(existing.id))
            raise RepositoryAlreadyExistsError(
                f"Repository {full_name} is already registered.",
            )
            
        collection_name = f"repo_{owner}_{name}".lower().replace("-", "_").replace(".", "_")
        repo_record = Repository(
            repo_name=name,
            repo_url=request.repo_url,
            source_type="github",
            default_branch=request.branch or "main",
            access_token_ref=request.pat_token,
            is_private=bool(request.pat_token),
            qdrant_collection_name=collection_name,
        )
        
        # Ensure the repository collection is created in Qdrant immediately
        logger.info("qdrant_collection_provisioning_started", collection=collection_name)
        try:
            from app.infrastructure.qdrant.collection_manager import ensure_collection_exists
            await ensure_collection_exists(repo_record.qdrant_collection_name)
            logger.info("qdrant_collection_provisioned_successfully", collection=collection_name)
        except Exception as e:
            logger.error("qdrant_collection_provisioning_failed", collection=collection_name, error=str(e), exc_info=e)
        
        created_repo = await self.repo.create(repo_record)
        logger.info("repository_registered_successfully", repo_id=str(created_repo.id), full_name=full_name, collection=collection_name)
        
        # Auto-trigger initial ingestion pipeline
        if self.job_repo is not None:
            try:
                from app.core.enums import TriggerSource, JobStatus
                from app.infrastructure.database.models.ingestion_job import IngestionJob
                from app.workers.tasks.ingestion_tasks import ingest_repository_task

                job = IngestionJob(
                    repo_id=created_repo.id,
                    job_type="full",
                    trigger_source=TriggerSource.GITHUB_URL.value,
                    status=JobStatus.QUEUED.value,
                    commit_sha="",
                )
                job = await self.job_repo.create(job)
                logger.info("auto_ingestion_job_created", job_id=str(job.id), repo_id=str(created_repo.id))

                ingest_repository_task.delay(
                    job_id=str(job.id),
                    repo_id=str(created_repo.id),
                    source=TriggerSource.GITHUB_URL.value,
                    commit_sha=None,
                )
                logger.info("auto_ingestion_task_dispatched", job_id=str(job.id), repo_id=str(created_repo.id))
            except Exception as e:
                logger.error("failed_to_auto_trigger_ingestion", repo_id=str(created_repo.id), error=str(e), exc_info=e)

        return created_repo

    async def get_repository(self, repo_id: RepoId | str) -> Repository:
        """
        Retrieve a repository by ID. Raises if not found.
        """
        logger.info("repository_fetch_started", repo_id=str(repo_id))
        repo = await self.repo.get_by_id(repo_id)
        if not repo:
            logger.warning("repository_fetch_not_found", repo_id=str(repo_id))
            raise RepositoryNotFoundError(f"Repository {repo_id} not found.")
        logger.info("repository_fetch_success", repo_id=str(repo.id), repo_name=repo.name)
        return repo

    async def list_repositories(self) -> Sequence[Repository]:
        """
        List all registered repositories.
        """
        logger.info("repositories_list_started")
        repos = await self.repo.list_all()
        logger.info("repositories_list_success", count=len(repos))
        return repos

    async def validate_repository_exists(self, repo_id: RepoId | str) -> bool:
        """
        Return True if repository exists, False otherwise.
        """
        repo = await self.repo.get_by_id(repo_id)
        exists = repo is not None
        logger.info("repository_existence_check", repo_id=str(repo_id), exists=exists)
        return exists

    async def update_repository(self, repo_id: RepoId | str, request: UpdateRepositoryRequest) -> Repository:
        """Update mutable fields of a repository."""
        logger.info("repository_update_started", repo_id=str(repo_id), branch=request.branch)
        repo = await self.get_repository(repo_id)
        
        update_data = {}
        if request.branch is not None:
            update_data["default_branch"] = request.branch
        if request.pat_token is not None:
            update_data["github_token"] = request.pat_token
            
        if update_data:
            await self.repo.update_fields(repo_id, update_data)
            repo = await self.get_repository(repo_id)
            logger.info("repository_update_success", repo_id=str(repo_id), updated_fields=list(update_data.keys()))
            
        return repo

    async def delete_repository(self, repo_id: RepoId | str) -> None:
        """Delete repository and attempt to drop its Qdrant collection."""
        logger.info("repository_deletion_started", repo_id=str(repo_id))
        repo = await self.get_repository(repo_id)
        
        # 1. Attempt to drop Qdrant collection
        try:
            logger.info("qdrant_collection_deletion_started", collection=repo.qdrant_collection_name)
            from app.infrastructure.qdrant.client import get_qdrant_client
            client = get_qdrant_client()
            await client.delete_collection(repo.qdrant_collection_name)
            logger.info("qdrant_collection_deleted", collection=repo.qdrant_collection_name)
        except Exception as e:
            logger.warning("qdrant_collection_deletion_failed", collection=repo.qdrant_collection_name, error=str(e))
            
        # 2. Delete from DB (cascades to jobs, chunks, etc if configured)
        await self.repo.delete(repo_id)
        logger.info("repository_deleted_successfully", repo_id=str(repo_id))
