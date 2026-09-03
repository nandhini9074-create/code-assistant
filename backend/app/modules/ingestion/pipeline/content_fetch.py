"""
app/modules/ingestion/pipeline/content_fetch.py
Pipeline stage: Fetch file content.
"""

import os

from app.core.enums import IngestionSource
from app.infrastructure.github.blobs_client import fetch_blob_content
from app.modules.ingestion.domain.ingestion_domain import IngestionContext
from app.modules.repositories.repository.repository_repo import RepositoryRepository


class ContentFetchStage:
    def __init__(
        self,
        repo_repo: RepositoryRepository,
    ) -> None:
        self.repo_repo = repo_repo

    async def execute(self, context: IngestionContext) -> None:
        """Fetches file content for all files in context."""
        repo = await self.repo_repo.get_by_id(context.repo_id)
        if not repo:
            return

        for file in context.files:
            if context.source == IngestionSource.ZIP_UPLOAD and context.extracted_zip_path:
                full_path = os.path.join(context.extracted_zip_path, file.file_path)
                try:
                    with open(full_path, "rb") as f:
                        file.content = f.read()
                        file.size = len(file.content)
                except Exception:
                    file.content = b""
            else:
                try:
                    content_bytes = await fetch_blob_content(repo.owner, repo.name, file.blob_sha)
                    file.content = content_bytes
                    file.size = len(file.content)
                except Exception:
                    file.content = b""
