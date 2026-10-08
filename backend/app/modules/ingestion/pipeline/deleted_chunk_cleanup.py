"""
app/modules/ingestion/pipeline/deleted_chunk_cleanup.py
Pipeline stage: Clean up deleted chunks.
"""

import uuid

from app.core.logging import get_logger
from app.infrastructure.qdrant.vector_repository import delete_vectors_by_file
from app.modules.ingestion.domain.ingestion_domain import IngestionContext
from app.modules.ingestion.repository.chunk_registry_repo import ChunkRegistryRepository
from app.modules.ingestion.repository.file_hash_repo import FileHashRepository
from app.modules.repositories.repository.repository_repo import RepositoryRepository

logger = get_logger(__name__)


class DeletedChunkCleanupStage:
    def __init__(
        self,
        repo_repo: RepositoryRepository,
        file_repo: FileHashRepository,
        chunk_repo: ChunkRegistryRepository,
    ) -> None:
        self.repo_repo = repo_repo
        self.file_repo = file_repo
        self.chunk_repo = chunk_repo

    async def execute(self, context: IngestionContext) -> None:
        """Removes chunks for deleted files from Qdrant and DB."""
        if not context.deleted_files:
            logger.info("stage_11_deleted_chunk_cleanup_skipped", reason="No deleted files detected")
            return
            
        logger.info("stage_11_deleted_chunk_cleanup_started", deleted_files_count=len(context.deleted_files))
        repo = await self.repo_repo.get_by_id(uuid.UUID(context.repo_id))
        if not repo:
            logger.error("stage_11_cleanup_aborted", reason="Repository not found")
            return
            
        # Delete from Qdrant
        for deleted_file in context.deleted_files:
            logger.info("stage_11_deleting_file_vectors", file_path=deleted_file, collection=repo.qdrant_collection_name)
            await delete_vectors_by_file(repo.qdrant_collection_name, context.repo_id, deleted_file)
            
        # Delete from DB
        repo_uuid = uuid.UUID(context.repo_id)
        await self.chunk_repo.delete_by_file_paths(repo_uuid, context.deleted_files)
        await self.file_repo.mark_deleted(repo_uuid, context.deleted_files)
        logger.info("stage_11_deleted_chunk_cleanup_completed", deleted_files_count=len(context.deleted_files))
