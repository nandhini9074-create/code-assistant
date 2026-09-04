"""
app/modules/repositories/schemas/repository_schema.py
Schemas for repository module.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import RepositoryStatus
from app.shared.schemas.base import BaseSchema
from app.shared.types.repo_types import RepoId


class CreateRepositoryRequest(BaseSchema):
    """Request to register a new repository."""
    repo_url: str = Field(..., description="Full GitHub URL (e.g., https://github.com/owner/repo)")
    branch: str | None = Field(default="main", description="Branch to index")
    pat_token: str | None = Field(default=None, description="Optional GitHub PAT to override global token")


class UpdateRepositoryRequest(BaseSchema):
    """Request to update a repository."""
    branch: str | None = Field(default=None, description="Branch to index")
    pat_token: str | None = Field(default=None, description="Optional GitHub PAT to override global token")


class RepositoryResponse(BaseSchema):
    """Response containing repository details."""
    id: RepoId
    name: str
    owner: str
    full_name: str
    github_url: str
    status: str
    current_commit_sha: str | None
    qdrant_collection: str
    
    model_config = ConfigDict(from_attributes=True)


class RepositoryListResponse(BaseSchema):
    """Response for a list of repositories."""
    repositories: list[RepositoryResponse]
