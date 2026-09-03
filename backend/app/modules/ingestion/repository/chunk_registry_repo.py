"""
app/modules/ingestion/repository/chunk_registry_repo.py
SQLAlchemy CRUD operations for ChunkRegistry model.
"""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import delete, select
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

    async def get_by_file_path(self, repo_id: RepoId, file_path: str) -> Sequence[ChunkRegistry]:
        stmt = select(ChunkRegistry).where(
            ChunkRegistry.repo_id == repo_id,
            ChunkRegistry.file_path == file_path
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_point_ids_by_file_paths(self, repo_id: RepoId, file_paths: list[str]) -> list[str]:
        if not file_paths:
            return []
            
        stmt = select(ChunkRegistry.point_id).where(
            ChunkRegistry.repo_id == repo_id,
            ChunkRegistry.file_path.in_(file_paths)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete_by_file_paths(self, repo_id: RepoId, file_paths: list[str]) -> bool:
        if not file_paths:
            return False
            
        stmt = delete(ChunkRegistry).where(
            ChunkRegistry.repo_id == repo_id,
            ChunkRegistry.file_path.in_(file_paths)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0
