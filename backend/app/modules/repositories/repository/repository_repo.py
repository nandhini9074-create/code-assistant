"""
app/modules/repositories/repository/repository_repo.py
SQLAlchemy repository pattern implementation for the Repository model.
"""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import RepositoryStatus
from app.infrastructure.database.models.repository import Repository
from app.shared.types.repo_types import RepoId


class RepositoryRepository:
    """Database repository for Repository entity."""
    
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, repository: Repository) -> Repository:
        """Create a new repository record."""
        self.session.add(repository)
        await self.session.commit()
        await self.session.refresh(repository)
        return repository

    async def get_by_id(self, repo_id: RepoId) -> Repository | None:
        """Get repository by ID."""
        return await self.session.get(Repository, repo_id)

    async def get_by_full_name(self, full_name: str) -> Repository | None:
        """Get repository by its full name (e.g. 'owner/repo')."""
        stmt = select(Repository).where(Repository.full_name == full_name)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(self, limit: int = 100, offset: int = 0) -> Sequence[Repository]:
        """List repositories."""
        stmt = select(Repository).limit(limit).offset(offset).order_by(Repository.created_at.desc())
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def update_status(self, repo_id: RepoId, status: RepositoryStatus) -> bool:
        """Update repository status."""
        stmt = (
            update(Repository)
            .where(Repository.id == repo_id)
            .values(status=status.value)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0

    async def update_commit_sha(self, repo_id: RepoId, commit_sha: str) -> bool:
        """Update repository's current commit SHA."""
        stmt = (
            update(Repository)
            .where(Repository.id == repo_id)
            .values(current_commit_sha=commit_sha)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0
