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
from app.modules.ingestion.schemas.ingestion_schema import IngestionJobResponse
from app.dependencies import get_ingestion_job_repo
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/repositories", tags=["Repositories"])


@router.post("/", response_model=RepositoryResponse, status_code=status.HTTP_201_CREATED)
async def register_repository(
    request: CreateRepositoryRequest,
    service: RepositoryService = Depends(get_repository_service),
) -> RepositoryResponse:
    """Register a new GitHub repository for indexing."""
    try:
        return await service.register_repository_with_response(request)
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


@router.post("/zip", response_model=IngestionJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_zip(
    file: UploadFile = File(...),
    repo_name: str = Form(...),
    service: RepositoryService = Depends(get_repository_service),
    job_repo: IngestionJobRepository = Depends(get_ingestion_job_repo),
) -> IngestionJobResponse:
    """Upload a ZIP file for repository ingestion."""
    if not file.filename or not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="Must be a ZIP file.")

    # Calculate ZIP fingerprint hash for versioning
    from app.infrastructure.storage.zip_storage import ZipStorageManager
    zip_hash = ZipStorageManager.calculate_zip_hash(file.file)
    commit_sha = f"zip_{zip_hash[:16]}"
        
    # Check if repo exists, if not create it
    url = f"local://{repo_name}"
    from app.infrastructure.database.models.repository import Repository
    
    existing = await service.repo.get_by_url(url)
    if not existing:
        existing = await service.repo.get_by_full_name(repo_name)
    if not existing:
        safe_collection_name = f"repo_local_{repo_name}".lower().replace("-", "_").replace("/", "_")
        repo_record = Repository(
            repo_name=repo_name,
            repo_url=url,
            source_type="local",
            default_branch="main",
            qdrant_collection_name=safe_collection_name,
        )
        existing = await service.repo.create(repo_record)
        
        # Provision collection in Qdrant immediately
        try:
            from app.infrastructure.qdrant.collection_manager import ensure_collection_exists
            await ensure_collection_exists(existing.qdrant_collection_name)
        except Exception as e:
            logger.error("qdrant_collection_provisioning_failed", collection=existing.qdrant_collection_name, error=str(e))
        
    # Create job
    from app.infrastructure.database.models.ingestion_job import IngestionJob
    from app.core.enums import TriggerSource, JobStatus
    
    job = IngestionJob(
        repo_id=existing.id,
        job_type="full",
        trigger_source=TriggerSource.ZIP_UPLOAD.value,
        status=JobStatus.PENDING.value,
        commit_sha=commit_sha,
    )
    job = await job_repo.create(job)
    
    from app.modules.ingestion.service.zip_ingestion_service import ZipIngestionService
    from app.dependencies import get_ingestion_service
    zip_service = ZipIngestionService(get_ingestion_service(service.repo, job_repo, service.repo.session))
    try:
        logger.info("starting_zip_ingestion", repo_name=repo_name, commit_sha=commit_sha, job_id=str(job.id))
        result = await zip_service.process_zip(
            job_id=str(job.id),
            repo_id=str(existing.id),
            repo_name=existing.name,
            commit_sha=commit_sha,
            zip_file=file.file
        )
        
        if not result.success:
            logger.error("zip_ingestion_failed", repo_name=repo_name, error=result.error_message)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.error_message or "Ingestion failed.")
            
        logger.info("zip_ingestion_completed", repo_name=repo_name, job_id=str(job.id), chunks=result.indexed_chunks_count)
        return IngestionJobResponse(
            job_id=str(job.id),
            repo_id=str(existing.id),
            status=JobStatus.COMPLETED.value,
            message="Repository successfully ingested and indexed from ZIP archive.",
            processed_files=result.processed_files_count,
            processed_chunks=result.indexed_chunks_count,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("zip_upload_processing_failed", repo_name=repo_name, error=str(exc), exc_info=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
