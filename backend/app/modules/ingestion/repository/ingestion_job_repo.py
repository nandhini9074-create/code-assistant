"""
app/modules/ingestion/repository/ingestion_job_repo.py
SQLAlchemy CRUD operations for IngestionJob model.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import JobStatus
from app.infrastructure.database.models.ingestion_job import IngestionJob
from app.shared.types.repo_types import JobId


class IngestionJobRepository:
    """Database repository for IngestionJob entity."""
    
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, job: IngestionJob) -> IngestionJob:
        self.session.add(job)
        await self.session.commit()
        await self.session.refresh(job)
        return job

    async def get_by_id(self, job_id: JobId) -> IngestionJob | None:
        return await self.session.get(IngestionJob, job_id)

    async def update_status(
        self,
        job_id: JobId,
        status: JobStatus,
        stage: str | None = None,
        error_info: dict[str, Any] | None = None,
    ) -> bool:
        values: dict[str, Any] = {"status": status.value}
        if stage:
            values["stage"] = stage
        if error_info:
            values["error_info"] = error_info
            
        stmt = update(IngestionJob).where(IngestionJob.id == job_id).values(**values)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0

    async def update_progress(
        self,
        job_id: JobId,
        processed_files: int | None = None,
        processed_chunks: int | None = None,
        checkpoint_data: dict[str, Any] | None = None,
    ) -> bool:
        values: dict[str, Any] = {}
        if processed_files is not None:
            values["processed_files"] = processed_files
        if processed_chunks is not None:
            values["processed_chunks"] = processed_chunks
        if checkpoint_data is not None:
            values["checkpoint_data"] = checkpoint_data
            
        if not values:
            return False
            
        stmt = update(IngestionJob).where(IngestionJob.id == job_id).values(**values)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0
