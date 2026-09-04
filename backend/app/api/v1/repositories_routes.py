"""
app/api/v1/repositories_routes.py
Repository management API routes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Response

from app.core.exceptions import RepositoryAlreadyExistsError, RepositoryNotFoundError
from app.dependencies import get_repository_service
from app.modules.repositories.schemas.repository_schema import (
    CreateRepositoryRequest,
    UpdateRepositoryRequest,
    RepositoryListResponse,
    RepositoryResponse,
)
from app.modules.repositories.service.repository_service import RepositoryService
from app.modules.ingestion.repository.ingestion_job_repo import IngestionJobRepository
from app.dependencies import get_ingestion_job_repo

router = APIRouter(prefix="/repositories", tags=["Repositories"])


@router.post("/", response_model=RepositoryResponse, status_code=status.HTTP_201_CREATED)
async def register_repository(
    request: CreateRepositoryRequest,
    service: RepositoryService = Depends(get_repository_service),
) -> RepositoryResponse:
    """Register a new GitHub repository for indexing."""
    try:
        repo = await service.register_repository(request)
        return RepositoryResponse.model_validate(repo)
    except RepositoryAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("/", response_model=RepositoryListResponse)
async def list_repositories(
    service: RepositoryService = Depends(get_repository_service),
) -> RepositoryListResponse:
    """List all registered repositories."""
    repos = await service.list_repositories()
    return RepositoryListResponse(
        repositories=[RepositoryResponse.model_validate(r) for r in repos]
    )


@router.get("/{repo_id}", response_model=RepositoryResponse)
async def get_repository(
    repo_id: str,
    service: RepositoryService = Depends(get_repository_service),
) -> RepositoryResponse:
    """Get details of a specific repository."""
    try:
        repo = await service.get_repository(repo_id)
        return RepositoryResponse.model_validate(repo)
    except RepositoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.patch("/{repo_id}", response_model=RepositoryResponse)
async def update_repository(
    repo_id: str,
    request: UpdateRepositoryRequest,
    service: RepositoryService = Depends(get_repository_service),
) -> RepositoryResponse:
    """Update a specific repository's mutable fields."""
    try:
        repo = await service.update_repository(repo_id, request)
        return RepositoryResponse.model_validate(repo)
    except RepositoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.delete("/{repo_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_repository(
    repo_id: str,
    service: RepositoryService = Depends(get_repository_service),
) -> Response:
    """Delete a repository and its associated data."""
    try:
        await service.delete_repository(repo_id)
    except RepositoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/zip", response_model=dict, status_code=status.HTTP_202_ACCEPTED)
async def upload_zip(
    file: UploadFile = File(...),
    repo_name: str = Form(...),
    service: RepositoryService = Depends(get_repository_service),
    job_repo: IngestionJobRepository = Depends(get_ingestion_job_repo),
) -> dict:
    """Upload a ZIP file for repository ingestion."""
    if not file.filename or not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="Must be a ZIP file.")
        
    # Check if repo exists, if not create it
    full_name = f"local/{repo_name}"
    from app.infrastructure.database.models.repository import Repository
    
    existing = await service.repo.get_by_full_name(full_name)
    if not existing:
        repo_record = Repository(
            repo_name=repo_name,
            repo_url=f"local://{repo_name}",
            source_type="local",
            default_branch="main",
            qdrant_collection_name=f"repo_local_{repo_name}".lower().replace("-", "_"),
        )
        existing = await service.repo.create(repo_record)
        
    # Create job
    from app.infrastructure.database.models.ingestion_job import IngestionJob
    from app.core.enums import TriggerSource, JobStatus
    
    job = IngestionJob(
        repo_id=existing.id,
        job_type="full",
        trigger_source=TriggerSource.ZIP_UPLOAD.value,
        status=JobStatus.PENDING.value,
        commit_sha="zip_upload",
    )
    job = await job_repo.create(job)
    
    from app.modules.ingestion.service.zip_ingestion_service import ZipIngestionService
    from app.dependencies import get_ingestion_service
    # Zip extraction takes time, but it needs to be synchronous here to grab the file upload before it closes.
    # The actual ingestion runs inside process_zip.
    zip_service = ZipIngestionService(get_ingestion_service(service.repo, job_repo, service.repo.session))
    try:
        result = await zip_service.process_zip(
            job_id=str(job.id),
            repo_id=str(existing.id),
            repo_name=existing.name,
            commit_sha="zip_upload",
            zip_file=file.file
        )
        return {"job_id": result.job_id, "status": "queued"}
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
