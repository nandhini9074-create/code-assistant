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
    repo_id: str = Field(..., description="UUID of the registered repository")
    branch: str | None = Field(default=None, description="Branch to ingest. Overrides default_branch if provided.")
    commit_sha: str | None = Field(default=None, description="Commit SHA to ingest (if specific commit)")


class IngestZipRequest(BaseSchema):
    """Request to ingest a repository from a ZIP upload."""
    commit_sha: str = Field(..., description="Commit SHA associated with the ZIP contents")


class IngestionJobResponse(BaseSchema):
    """Response containing basic ingestion job details."""
    job_id: str
    repo_id: str
    status: str
    message: str | None = None
    stage: str | None = None
    processed_files: int = 0
    processed_chunks: int = 0
    error_info: dict[str, Any] | None = None
