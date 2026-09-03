"""
app/modules/jobs/schemas/job_schema.py
Schemas for the jobs module.
"""

from datetime import datetime
from typing import Any

from app.core.enums import JobStatus
from app.shared.schemas.base import BaseSchema


class JobStatusResponse(BaseSchema):
    """Response containing job status details."""
    id: str
    status: JobStatus
    stage: str | None = None
    processed_files_count: int = 0
    indexed_chunks_count: int = 0
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
