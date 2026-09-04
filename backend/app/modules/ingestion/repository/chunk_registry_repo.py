"""
app/modules/ingestion/repository/chunk_registry_repo.py
SQLAlchemy CRUD operations for ChunkRegistry model.
"""

from __future__ import annotations

from typing import Sequence, cast

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models.chunk_registry import ChunkRegistry
from app.shared.types.repo_types import RepoId


class ChunkRegistryRepository:
    """Database repository for ChunkRegistry entity."""
    
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def bulk_create(self, chunks: list[ChunkRegistry]) -> None:
        self.session.add_all(chunks)
        await self.session.commit()

    async def get_by_file_path(self, repo_id: RepoId | str, file_path: str) -> Sequence[ChunkRegistry]:
        import uuid
        uid = uuid.UUID(repo_id) if isinstance(repo_id, str) else repo_id
        stmt = select(ChunkRegistry).where(
            ChunkRegistry.repo_id == uid,
            ChunkRegistry.file_path == file_path
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_point_ids_by_file_paths(self, repo_id: RepoId | str, file_paths: list[str]) -> list[str]:
        if not file_paths:
            return []
            
        import uuid
        uid = uuid.UUID(repo_id) if isinstance(repo_id, str) else repo_id
        stmt = select(ChunkRegistry.qdrant_point_id).where(
            ChunkRegistry.repo_id == uid,
            ChunkRegistry.file_path.in_(file_paths),
            ChunkRegistry.qdrant_point_id.is_not(None)
        )
        result = await self.session.execute(stmt)
        return [point_id for point_id in result.scalars().all() if point_id is not None]

    async def delete_by_file_paths(self, repo_id: RepoId | str, file_paths: list[str]) -> bool:
        if not file_paths:
            return False
            
        import uuid
        uid = uuid.UUID(repo_id) if isinstance(repo_id, str) else repo_id
        stmt = delete(ChunkRegistry).where(
            ChunkRegistry.repo_id == uid,
            ChunkRegistry.file_path.in_(file_paths)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return cast(CursorResult[None], result).rowcount > 0
