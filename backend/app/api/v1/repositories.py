"""
app/api/v1/repositories.py
API endpoints for managing GitHub repositories.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import RepositoryStatus
from app.infrastructure.database.models.repository import Repository
from app.infrastructure.database.session import get_db

router = APIRouter(prefix="/repositories", tags=["Repositories"])


@router.post("/", status_code=201)
async def register_repository(
    name: str,
    owner: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Register a new GitHub repository for indexing.
    """
    full_name = f"{owner}/{name}"
    github_url = f"https://github.com/{full_name}"

    # Check if exists
    result = await db.execute(
        select(Repository).where(Repository.full_name == full_name)
    )
    existing = result.scalar_one_or_none()
    
    if existing:
        raise HTTPException(
            status_code=409, 
            detail=f"Repository {full_name} is already registered."
        )

    repo = Repository(
        name=name,
        owner=owner,
        full_name=full_name,
        github_url=github_url,
        status=RepositoryStatus.PENDING.value,
        # Determine deterministic Qdrant collection name
        qdrant_collection=f"repo_{owner}_{name}".lower().replace("-", "_"),
    )
    
    db.add(repo)
    await db.commit()
    await db.refresh(repo)
    
    return {
        "id": str(repo.id),
        "full_name": repo.full_name,
        "status": repo.status,
    }


@router.get("/{repo_id}")
async def get_repository_status(
    repo_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Get the status of a registered repository.
    """
    repo = await db.get(Repository, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found.")
        
    return {
        "id": str(repo.id),
        "full_name": repo.full_name,
        "status": repo.status,
        "current_commit_sha": repo.current_commit_sha,
        "qdrant_collection": repo.qdrant_collection,
    }
