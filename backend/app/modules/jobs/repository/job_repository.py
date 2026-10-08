"""
app/modules/jobs/repository/job_repository.py
Repository for jobs module.
"""

from typing import cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models.ingestion_job import IngestionJob


class JobRepository:
    """Repository for querying ingestion jobs."""
    
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_job(self, job_id: str) -> IngestionJob | None:
        """Get a job by its ID."""
        try:
            uuid_obj = UUID(job_id)
        except ValueError:
            return None
            
        result = await self.session.execute(
            select(IngestionJob).where(IngestionJob.id == uuid_obj)
        )
        return result.scalar_one_or_none()

    async def list_jobs_for_repo(self, repo_id: str, limit: int = 50, offset: int = 0) -> list[IngestionJob]:
        """List jobs for a specific repository."""
        try:
            repo_uuid = UUID(repo_id)
        except ValueError:
            return []
            
        result = await self.session.execute(
            select(IngestionJob)
            .where(IngestionJob.repo_id == repo_uuid)
            .order_by(IngestionJob.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def update_status(self, job_id: str, status: str) -> bool:
        """Update job status."""
        try:
            uuid_obj = UUID(job_id)
        except ValueError:
            return False
            
        stmt = (
            update(IngestionJob)
            .where(IngestionJob.id == uuid_obj)
            .values(status=status)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return cast(CursorResult[None], result).rowcount > 0
