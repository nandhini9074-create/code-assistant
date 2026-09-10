"""
app/modules/repositories/service/repository_service.py
Service for repository business logic.
"""

from __future__ import annotations

from typing import Sequence

import uuid

from app.config import get_settings
from app.core.enums import RepositoryStatus
from app.core.exceptions import RepositoryAlreadyExistsError, RepositoryNotFoundError
from app.core.logging import get_logger
from app.infrastructure.database.models.repository import Repository
from app.modules.repositories.repository.repository_repo import RepositoryRepository
from app.modules.repositories.schemas.repository_schema import (
    CreateRepositoryRequest,
    RepositoryResponse,
    UpdateRepositoryRequest,
)
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
        Validate URL, check for duplicates, register a new repository,
        auto-create a GitHub webhook, and trigger initial indexing.

        Returns a Repository ORM instance. Callers that need webhook_configured
        should use register_repository_with_response() instead.
        """
        repo, _, _ = await self._register_repository_internal(request)
        return repo

    async def register_repository_with_response(self, request: CreateRepositoryRequest) -> RepositoryResponse:
        """
        Same as register_repository but returns a RepositoryResponse with
        webhook_configured and webhook_error populated.
        """
        repo, webhook_configured, webhook_error = await self._register_repository_internal(request)
        response = RepositoryResponse.model_validate(repo)
        response.webhook_configured = webhook_configured
        response.webhook_error = webhook_error
        return response

    async def _register_repository_internal(
        self,
        request: CreateRepositoryRequest,
    ) -> tuple[Repository, bool, str | None]:
        """
        Core registration logic. Returns (repo, webhook_configured, safe_error_msg).
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

        # --- Step 5: Auto-create GitHub webhook ---
        webhook_configured = False
        webhook_error: str | None = None
        webhook_configured, webhook_error = await self._setup_github_webhook(
            repo_id=str(created_repo.id),
            owner=owner,
            repo_name=name,
            pat_token=request.pat_token,
        )

        # --- Step 6: Auto-trigger initial ingestion pipeline ---
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

        return created_repo, webhook_configured, webhook_error

    async def _setup_github_webhook(
        self,
        repo_id: str,
        owner: str,
        repo_name: str,
        pat_token: str | None,
    ) -> tuple[bool, str | None]:
        """
        Attempt to create a GitHub webhook for the repository.

        Returns (success: bool, safe_error_message: str | None).
        Never raises — webhook failure is non-fatal for registration.
        Never logs PAT or webhook secret.
        """
        from app.core.exceptions import GitHubWebhookError
        from app.infrastructure.github.hooks_client import create_webhook

        settings = get_settings()

        if not pat_token:
            logger.info(
                "github_webhook_setup_skipped",
                repo_id=repo_id,
                reason="No PAT provided — cannot authenticate to GitHub Hooks API",
            )
            return False, "No GitHub token provided; webhook must be configured manually."

        if not settings.github_webhook_secret:
            logger.warning(
                "github_webhook_setup_skipped",
                repo_id=repo_id,
                reason="GITHUB_WEBHOOK_SECRET is not configured",
            )
            return False, "Webhook secret is not configured on the server."

        if "localhost" in settings.app_base_url or "127.0.0.1" in settings.app_base_url:
            logger.warning(
                "github_webhook_setup_skipped",
                repo_id=repo_id,
                reason="APP_BASE_URL is localhost — GitHub cannot reach it",
                app_base_url=settings.app_base_url,
            )
            return False, (
                f"APP_BASE_URL is set to '{settings.app_base_url}' which is not publicly reachable. "
                "Configure APP_BASE_URL to your public/ngrok URL."
            )

        payload_url = settings.webhook_payload_url

        try:
            webhook_id = await create_webhook(
                owner=owner,
                repo=repo_name,
                payload_url=payload_url,
                secret=settings.github_webhook_secret,
                github_token=pat_token,   # NOT logged
            )
            # Persist the webhook ID so we can delete it later
            await self.repo.update_fields(repo_id, {"github_webhook_id": webhook_id})
            logger.info(
                "github_webhook_id_stored",
                repo_id=repo_id,
                webhook_id=webhook_id,
            )
            return True, None

        except GitHubWebhookError as exc:
            logger.warning(
                "github_webhook_creation_failed",
                repo_id=repo_id,
                owner=owner,
                repo_name=repo_name,
                status_code=exc.details.get("github_status_code"),
                reason=exc.safe_reason,
                # NOT logged: pat_token, webhook secret
            )
            return False, exc.safe_reason

        except Exception as exc:
            logger.error(
                "github_webhook_creation_unexpected_error",
                repo_id=repo_id,
                owner=owner,
                repo_name=repo_name,
                error=str(exc),
                exc_info=exc,
            )
            return False, "An unexpected error occurred while configuring the GitHub webhook."

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
        """Delete repository: remove GitHub webhook, drop Qdrant collection, delete DB record."""
        logger.info("repository_deletion_started", repo_id=str(repo_id))
        repo = await self.get_repository(repo_id)

        # --- Step 1: Delete GitHub webhook if we have one ---
        if repo.github_webhook_id is not None and repo.access_token_ref:
            owner = repo.owner
            repo_name = repo.repo_name
            webhook_id = repo.github_webhook_id
            logger.info(
                "github_webhook_deletion_started",
                repo_id=str(repo_id),
                owner=owner,
                repo_name=repo_name,
                webhook_id=webhook_id,
            )
            try:
                from app.infrastructure.github.hooks_client import delete_webhook
                await delete_webhook(
                    owner=owner,
                    repo=repo_name,
                    webhook_id=webhook_id,
                    github_token=repo.access_token_ref,  # NOT logged
                )
            except Exception as exc:
                # Non-fatal: log and continue with local deletion
                logger.warning(
                    "github_webhook_deletion_failed",
                    repo_id=str(repo_id),
                    webhook_id=webhook_id,
                    error=str(exc),
                    reason="Local repository will still be deleted",
                )
        elif repo.github_webhook_id is not None and not repo.access_token_ref:
            logger.warning(
                "github_webhook_deletion_skipped",
                repo_id=str(repo_id),
                webhook_id=repo.github_webhook_id,
                reason="No token available to authenticate with GitHub",
            )

        # --- Step 2: Drop Qdrant collection ---
        try:
            logger.info("qdrant_collection_deletion_started", collection=repo.qdrant_collection_name)
            from app.infrastructure.qdrant.client import get_qdrant_client
            client = get_qdrant_client()
            await client.delete_collection(repo.qdrant_collection_name)
            logger.info("qdrant_collection_deleted", collection=repo.qdrant_collection_name)
        except Exception as e:
            logger.warning("qdrant_collection_deletion_failed", collection=repo.qdrant_collection_name, error=str(e))
            
        # --- Step 3: Delete from DB (cascades to jobs, chunks, etc) ---
        await self.repo.delete(repo_id)
        logger.info("repository_deleted_successfully", repo_id=str(repo_id))
