"""
app/api/v1/repositories_routes.py
Repository management API routes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.exceptions import RepositoryAlreadyExistsError, RepositoryNotFoundError
from app.dependencies import get_repository_service
from app.modules.repositories.schemas.repository_schema import (
    CreateRepositoryRequest,
    RepositoryListResponse,
    RepositoryResponse,
)
from app.modules.repositories.service.repository_service import RepositoryService

router = APIRouter(prefix="/repositories", tags=["Repositories"])


@router.post("/", response_model=RepositoryResponse, status_code=status.HTTP_201_CREATED)
async def register_repository(
    request: CreateRepositoryRequest,
    service: RepositoryService = Depends(get_repository_service),
) -> RepositoryResponse:
    """Register a new GitHub repository for indexing."""
    try:
        return await service.register_repository(request)
    except RepositoryAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("/", response_model=RepositoryListResponse)
async def list_repositories(
    service: RepositoryService = Depends(get_repository_service),
) -> RepositoryListResponse:
    """List all registered repositories."""
    return await service.list_repositories()


@router.get("/{repo_id}", response_model=RepositoryResponse)
async def get_repository(
    repo_id: str,
    service: RepositoryService = Depends(get_repository_service),
) -> RepositoryResponse:
    """Get details of a specific repository."""
    try:
        return await service.get_repository(repo_id)
    except RepositoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
