"""
app/modules/ingestion/repository/file_registry_repo.py
SQLAlchemy CRUD operations for FileRegistry model.
"""

from __future__ import annotations

from typing import Sequence, cast

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import FileStatus
from app.infrastructure.database.models.file_registry import FileRegistry
from app.shared.types.repo_types import RepoId


class FileRegistryRepository:
    """Database repository for FileRegistry entity."""
    
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_file(self, file_record: FileRegistry) -> FileRegistry:
        # Simplified upsert for this implementation
        stmt = select(FileRegistry).where(
            FileRegistry.repo_id == file_record.repo_id,
            FileRegistry.file_path == file_record.file_path
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()
        
        if existing:
            existing.file_hash = file_record.file_hash
            existing.blob_sha = file_record.blob_sha
            existing.commit_sha = file_record.commit_sha
            existing.status = file_record.status
            file_record = existing
        else:
            self.session.add(file_record)
            
        await self.session.commit()
        await self.session.refresh(file_record)
        return file_record

    async def get_by_path(self, repo_id: RepoId, file_path: str) -> FileRegistry | None:
        stmt = select(FileRegistry).where(
            FileRegistry.repo_id == repo_id,
            FileRegistry.file_path == file_path
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_files(self, repo_id: RepoId) -> Sequence[FileRegistry]:
        stmt = select(FileRegistry).where(
            FileRegistry.repo_id == repo_id,
            FileRegistry.status == FileStatus.ACTIVE.value
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
        
    async def mark_deleted(self, repo_id: RepoId, file_paths: list[str]) -> bool:
        if not file_paths:
            return False
            
        # Instead of physically deleting, we could mark as DELETED
        # For simplicity, we'll actually delete them from registry in this mock,
        # or properly update status depending on requirements.
        stmt = delete(FileRegistry).where(
            FileRegistry.repo_id == repo_id,
            FileRegistry.file_path.in_(file_paths)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return cast(CursorResult[None], result).rowcount > 0
