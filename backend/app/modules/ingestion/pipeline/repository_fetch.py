"""
app/modules/ingestion/pipeline/repository_fetch.py
Pipeline stage: Fetch repo tree.
"""

import os

from app.core.enums import IngestionSource
from app.infrastructure.github.trees_client import fetch_repository_tree
from app.modules.ingestion.domain.ingestion_domain import FileRecord, IngestionContext
from app.modules.repositories.repository.repository_repo import RepositoryRepository


class RepositoryFetchStage:
    def __init__(
        self,
        repo_repo: RepositoryRepository,
    ) -> None:
        self.repo_repo = repo_repo

    async def execute(self, context: IngestionContext) -> None:
        """Fetches the repository file structure."""
        repo = await self.repo_repo.get_by_id(context.repo_id)
        if not repo:
            return

        if context.source == IngestionSource.ZIP_UPLOAD and context.extracted_zip_path:
            # Local ZIP extraction
            self._fetch_from_local(context, context.extracted_zip_path)
        else:
            # GitHub API fetch
            await self._fetch_from_github(context, repo.owner, repo.name)

    def _fetch_from_local(self, context: IngestionContext, base_path: str) -> None:
        for root, _, files in os.walk(base_path):
            for file_name in files:
                full_path = os.path.join(root, file_name)
                rel_path = os.path.relpath(full_path, base_path)
                # Ensure forward slashes for cross-platform consistency
                rel_path = rel_path.replace("\\", "/")
                
                context.files.append(
                    FileRecord(
                        file_path=rel_path,
                        blob_sha="",  # Not applicable for ZIP
                        file_hash="", # To be computed later
                    )
                )

    async def _fetch_from_github(self, context: IngestionContext, owner: str, repo: str) -> None:
        tree = await fetch_repository_tree(owner, repo, context.commit_sha, context.github_token)
        for item in tree:
            if item.get("type") == "blob":
                context.files.append(
                    FileRecord(
                        file_path=item["path"],
                        blob_sha=item["sha"],
                        file_hash="", # To be computed after content fetch
                    )
                )
