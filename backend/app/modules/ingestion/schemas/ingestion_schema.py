"""
app/modules/ingestion/schemas/ingestion_schema.py
Schemas for ingestion module.
"""

from typing import Any

from pydantic import Field

from app.shared.schemas.base import BaseSchema
from app.shared.types.repo_types import JobId


class IngestRepositoryRequest(BaseSchema):
    """Request to ingest a registered repository from GitHub."""
    branch: str | None = Field(default=None, description="Branch to ingest. Overrides default_branch if provided.")


class IngestZipRequest(BaseSchema):
    """Request to ingest a repository from a ZIP upload."""
    commit_sha: str = Field(..., description="Commit SHA associated with the ZIP contents")


class IngestionJobResponse(BaseSchema):
    """Response containing basic ingestion job details."""
    job_id: JobId
    repo_id: str
    status: str
    stage: str
    processed_files: int
    processed_chunks: int
    error_info: dict[str, Any] | None = None
