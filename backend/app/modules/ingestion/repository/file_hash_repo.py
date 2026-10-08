"""
app/modules/ingestion/repository/file_hash_repo.py
SQLAlchemy CRUD operations for FileHash model.
"""

from __future__ import annotations

from typing import Sequence, cast

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import FileStatus
from app.infrastructure.database.models.file_hash import FileHash
from app.shared.types.repo_types import RepoId


class FileHashRepository:
    """Database repository for FileHash entity."""
    
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_file(self, file_record: FileHash) -> FileHash:
        stmt = select(FileHash).where(
            FileHash.repo_id == file_record.repo_id,
            FileHash.file_path == file_record.file_path
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()
        
        if existing:
            existing.file_hash = file_record.file_hash
            existing.blob_sha = file_record.blob_sha
            existing.last_commit_sha = file_record.last_commit_sha
            existing.status = file_record.status
            file_record = existing
        else:
            self.session.add(file_record)
            
        await self.session.flush()
        return file_record

    async def get_by_path(self, repo_id: RepoId | str, file_path: str) -> FileHash | None:
        import uuid
        uid = uuid.UUID(repo_id) if isinstance(repo_id, str) else repo_id
        stmt = select(FileHash).where(
            FileHash.repo_id == uid,
            FileHash.file_path == file_path
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_files(self, repo_id: RepoId | str) -> Sequence[FileHash]:
        import uuid
        uid = uuid.UUID(repo_id) if isinstance(repo_id, str) else repo_id
        stmt = select(FileHash).where(
            FileHash.repo_id == uid,
            FileHash.status == FileStatus.ACTIVE.value
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
        
    async def mark_deleted(self, repo_id: RepoId | str, file_paths: list[str]) -> bool:
        if not file_paths:
            return False
        import uuid
        uid = uuid.UUID(repo_id) if isinstance(repo_id, str) else repo_id
        stmt = delete(FileHash).where(
            FileHash.repo_id == uid,
            FileHash.file_path.in_(file_paths)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return cast(CursorResult[None], result).rowcount > 0
