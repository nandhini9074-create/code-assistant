"""
app/modules/ingestion/pipeline/content_fetch.py
Pipeline stage: Fetch file content.
"""

import os
import uuid

from app.core.enums import FileFetchStatus, TriggerSource
from app.core.logging import get_logger
from app.infrastructure.github.blobs_client import fetch_blob_content
from app.modules.ingestion.domain.ingestion_domain import IngestionContext
from app.modules.repositories.repository.repository_repo import RepositoryRepository

logger = get_logger(__name__)


class ContentFetchStage:
    def __init__(
        self,
        repo_repo: RepositoryRepository,
    ) -> None:
        self.repo_repo = repo_repo

    async def execute(self, context: IngestionContext) -> None:
        """Fetches file content for all files in context."""
        logger.info("stage_4_content_fetch_started", total_files=len(context.files))
        repo = await self.repo_repo.get_by_id(uuid.UUID(context.repo_id))
        if not repo:
            logger.error("stage_4_content_fetch_aborted", reason="Repository not found")
            return

        success_count = 0
        error_count = 0

        for file in context.files:
            if context.source == TriggerSource.ZIP_UPLOAD and context.extracted_zip_path:
                full_path = os.path.join(context.extracted_zip_path, file.file_path)
                try:
                    with open(full_path, "rb") as f:
                        file.content = f.read()
                        file.size = len(file.content)
                    file.fetch_status = FileFetchStatus.SUCCESS
                    file.fetch_error = None
                    success_count += 1
                except Exception as exc:
                    logger.warning("stage_4_local_file_read_failed", file_path=file.file_path, error=str(exc))
                    file.content = b""
                    file.fetch_status = FileFetchStatus.FAILED
                    file.fetch_error = str(exc)
                    error_count += 1
            else:
                try:
                    parts = repo.repo_url.rstrip("/").split("/")
                    owner = parts[-2]
                    repo_slug = parts[-1].removesuffix(".git")
                    content_bytes = await fetch_blob_content(owner, repo_slug, file.blob_sha, context.github_token)
                    file.content = content_bytes
                    file.size = len(file.content)
                    file.fetch_status = FileFetchStatus.SUCCESS
                    file.fetch_error = None
                    success_count += 1
                except Exception as exc:
                    logger.warning("stage_4_github_blob_fetch_failed", file_path=file.file_path, blob_sha=file.blob_sha, error=str(exc))
                    file.content = b""
                    file.fetch_status = FileFetchStatus.FAILED
                    file.fetch_error = str(exc)
                    error_count += 1

        logger.info("stage_4_content_fetch_completed", total=len(context.files), success=success_count, failed=error_count)
