"""
app/modules/ingestion/pipeline/repository_fetch.py
Pipeline stage: Fetch repo tree.
"""

import os
import uuid

from app.core.enums import TriggerSource
from app.core.logging import get_logger
from app.infrastructure.github.trees_client import fetch_repository_tree
from app.modules.ingestion.domain.ingestion_domain import FileRecord, IngestionContext
from app.modules.repositories.repository.repository_repo import RepositoryRepository

logger = get_logger(__name__)


class RepositoryFetchStage:
    def __init__(
        self,
        repo_repo: RepositoryRepository,
    ) -> None:
        self.repo_repo = repo_repo

    async def execute(self, context: IngestionContext) -> None:
        """Fetches the repository file structure."""
        logger.info("stage_2_repository_fetch_started", repo_id=context.repo_id, source=str(context.source))
        repo = await self.repo_repo.get_by_id(uuid.UUID(context.repo_id))
        if not repo:
            logger.error("stage_2_repository_fetch_aborted", reason="Repository record not found")
            return

        if context.source == TriggerSource.ZIP_UPLOAD and context.extracted_zip_path:
            # Local ZIP extraction
            logger.info("stage_2_fetching_from_local_zip", path=context.extracted_zip_path)
            self._fetch_from_local(context, context.extracted_zip_path)
        else:
            # GitHub API fetch — parse owner/slug from repo_url
            parts = repo.repo_url.rstrip("/").split("/")
            owner = parts[-2]
            repo_slug = parts[-1].removesuffix(".git")
            target_ref = context.commit_sha or repo.default_branch or "main"
            logger.info("stage_2_fetching_from_github_api", owner=owner, repo=repo_slug, commit_sha=target_ref)
            await self._fetch_from_github(context, owner, repo_slug, target_ref)
        
        logger.info("stage_2_repository_fetch_completed", total_files_fetched=len(context.files))

    def _fetch_from_local(self, context: IngestionContext, base_path: str) -> None:
        for root, _, files in os.walk(base_path):
            for file_name in files:
                full_path = os.path.join(root, file_name)
                rel_path = os.path.relpath(full_path, base_path)
                rel_path = rel_path.replace("\\", "/")
                
                size = os.path.getsize(full_path)
                context.files.append(
                    FileRecord(
                        file_path=rel_path,
                        blob_sha="",
                        file_hash="",
                        size=size,
                    )
                )

    async def _fetch_from_github(self, context: IngestionContext, owner: str, repo: str, target_ref: str) -> None:
        try:
            tree = await fetch_repository_tree(owner, repo, target_ref, context.github_token)
            for item in tree:
                if item.get("type") == "blob":
                    context.files.append(
                        FileRecord(
                            file_path=item["path"],
                            blob_sha=item["sha"],
                            file_hash="",
                            size=item.get("size", 0),
                        )
                    )
        except Exception as exc:
            logger.error("stage_2_github_tree_fetch_failed", owner=owner, repo=repo, error=str(exc), exc_info=exc)
            raise
