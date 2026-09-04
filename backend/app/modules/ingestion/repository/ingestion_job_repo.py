"""
app/modules/ingestion/repository/ingestion_job_repo.py
SQLAlchemy CRUD operations for IngestionJob model.
"""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
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

    async def get_by_id(self, job_id: JobId | str) -> IngestionJob | None:
        import uuid
        uid = uuid.UUID(job_id) if isinstance(job_id, str) else job_id
        return await self.session.get(IngestionJob, uid)

    async def update_status(
        self,
        job_id: JobId | str,
        status: JobStatus,
        stage: str | None = None,
        error_info: dict[str, Any] | None = None,
    ) -> bool:
        import uuid
        uid = uuid.UUID(job_id) if isinstance(job_id, str) else job_id
        values: dict[str, Any] = {"status": status.value}
        if error_info:
            values["error_message"] = str(error_info.get("error", error_info))
            
        stmt = update(IngestionJob).where(IngestionJob.id == uid).values(**values)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return cast(CursorResult[None], result).rowcount > 0

    async def update_progress(
        self,
        job_id: JobId | str,
        processed_files: int | None = None,
        processed_chunks: int | None = None,
        checkpoint_data: dict[str, Any] | None = None,
    ) -> bool:
        import uuid
        uid = uuid.UUID(job_id) if isinstance(job_id, str) else job_id
        values: dict[str, Any] = {}
        if processed_files is not None:
            values["files_changed"] = processed_files
        if processed_chunks is not None:
            values["chunks_upserted"] = processed_chunks
            
        if not values:
            return False
            
        stmt = update(IngestionJob).where(IngestionJob.id == uid).values(**values)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return cast(CursorResult[None], result).rowcount > 0
