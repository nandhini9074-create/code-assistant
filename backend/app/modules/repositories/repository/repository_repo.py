"""
app/modules/repositories/repository/repository_repo.py
SQLAlchemy repository pattern implementation for the Repository model.
"""

from __future__ import annotations

from typing import Sequence, cast

from sqlalchemy import delete, select, update
from sqlalchemy.engine import CursorResult
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

    async def get_by_id(self, repo_id: RepoId | str) -> Repository | None:
        """Get repository by ID."""
        import uuid
        uid = uuid.UUID(repo_id) if isinstance(repo_id, str) else repo_id
        return await self.session.get(Repository, uid)

    async def get_by_url(self, repo_url: str) -> Repository | None:
        """Get repository by its URL."""
        stmt = select(Repository).where(Repository.repo_url == repo_url)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_full_name(self, full_name: str) -> Repository | None:
        """Get repository by full name or name."""
        stmt = select(Repository).where(
            (Repository.repo_name == full_name) | 
            (Repository.repo_url.endswith(full_name)) |
            (Repository.repo_url.endswith(f"{full_name}.git"))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(self, limit: int = 100, offset: int = 0) -> Sequence[Repository]:
        """List repositories."""
        stmt = select(Repository).limit(limit).offset(offset).order_by(Repository.created_at.desc())
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def update_status(self, repo_id: RepoId | str, status: RepositoryStatus) -> bool:
        """Update repository status."""
        import uuid
        uid = uuid.UUID(repo_id) if isinstance(repo_id, str) else repo_id
        stmt = (
            update(Repository)
            .where(Repository.id == uid)
            .values(status=status.value)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return cast(CursorResult[None], result).rowcount > 0

    async def update_commit_sha(self, repo_id: RepoId | str, commit_sha: str) -> bool:
        """Update repository's current commit SHA."""
        import uuid
        uid = uuid.UUID(repo_id) if isinstance(repo_id, str) else repo_id
        stmt = (
            update(Repository)
            .where(Repository.id == uid)
            .values(current_commit_sha=commit_sha)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return cast(CursorResult[None], result).rowcount > 0

    async def update_fields(self, repo_id: RepoId | str, data: dict) -> bool:
        """Update multiple fields on a repository."""
        if not data:
            return False
        import uuid
        uid = uuid.UUID(repo_id) if isinstance(repo_id, str) else repo_id
        stmt = (
            update(Repository)
            .where(Repository.id == uid)
            .values(**data)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return cast(CursorResult[None], result).rowcount > 0

    async def delete(self, repo_id: RepoId | str) -> bool:
        """Delete a repository."""
        import uuid
        uid = uuid.UUID(repo_id) if isinstance(repo_id, str) else repo_id
        stmt = delete(Repository).where(Repository.id == uid)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return cast(CursorResult[None], result).rowcount > 0
