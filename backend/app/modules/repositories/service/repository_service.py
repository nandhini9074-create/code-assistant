"""
app/modules/repositories/service/repository_service.py
Service for repository business logic.
"""

from __future__ import annotations

from typing import Sequence

from app.core.enums import RepositoryStatus
from app.core.exceptions import RepositoryAlreadyExistsError, RepositoryNotFoundError
from app.infrastructure.database.models.repository import Repository
from app.modules.repositories.repository.repository_repo import RepositoryRepository
from app.modules.repositories.schemas.repository_schema import CreateRepositoryRequest
from app.modules.repositories.validators.github_url_validator import validate_and_parse_github_url
from app.shared.types.repo_types import RepoId


class RepositoryService:
    """Service layer for managing repositories."""
    
    def __init__(self, repo: RepositoryRepository) -> None:
        self.repo = repo

    async def register_repository(self, request: CreateRepositoryRequest) -> Repository:
        """
        Validate URL, check for duplicates, and register a new repository.
        """
        owner, name = validate_and_parse_github_url(request.github_url)
        full_name = f"{owner}/{name}"
        
        existing = await self.repo.get_by_full_name(full_name)
        if existing:
            raise RepositoryAlreadyExistsError(
                f"Repository {full_name} is already registered.",
            )
            
        repo_record = Repository(
            name=name,
            owner=owner,
            full_name=full_name,
            github_url=request.github_url,
            default_branch=request.branch or "main",
            github_token=request.github_token,
            status=RepositoryStatus.PENDING.value,
            qdrant_collection=f"repo_{owner}_{name}".lower().replace("-", "_"),
        )
        
        return await self.repo.create(repo_record)

    async def get_repository(self, repo_id: RepoId) -> Repository:
        """
        Retrieve a repository by ID. Raises if not found.
        """
        repo = await self.repo.get_by_id(repo_id)
        if not repo:
            raise RepositoryNotFoundError(f"Repository {repo_id} not found.")
        return repo

    async def list_repositories(self) -> Sequence[Repository]:
        """
        List all registered repositories.
        """
        return await self.repo.list_all()

    async def validate_repository_exists(self, repo_id: RepoId) -> bool:
        """
        Return True if repository exists, False otherwise.
        """
        repo = await self.repo.get_by_id(repo_id)
        return repo is not None
