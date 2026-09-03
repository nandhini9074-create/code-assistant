"""
app/modules/ingestion/pipeline/deleted_chunk_cleanup.py
Pipeline stage: Clean up deleted chunks.
"""

from app.infrastructure.qdrant.vector_repository import delete_vectors_by_file
from app.modules.ingestion.domain.ingestion_domain import IngestionContext
from app.modules.ingestion.repository.chunk_registry_repo import ChunkRegistryRepository
from app.modules.ingestion.repository.file_registry_repo import FileRegistryRepository
from app.modules.repositories.repository.repository_repo import RepositoryRepository


class DeletedChunkCleanupStage:
    def __init__(
        self,
        repo_repo: RepositoryRepository,
        file_repo: FileRegistryRepository,
        chunk_repo: ChunkRegistryRepository,
    ) -> None:
        self.repo_repo = repo_repo
        self.file_repo = file_repo
        self.chunk_repo = chunk_repo

    async def execute(self, context: IngestionContext) -> None:
        """Removes chunks for deleted files from Qdrant and DB."""
        if not context.deleted_files:
            return
            
        repo = await self.repo_repo.get_by_id(context.repo_id)
        if not repo:
            return
            
        # Delete from Qdrant
        for deleted_file in context.deleted_files:
            await delete_vectors_by_file(repo.qdrant_collection, str(context.repo_id), deleted_file)
            
        # Delete from DB
        await self.chunk_repo.delete_by_file_paths(context.repo_id, context.deleted_files)
        await self.file_repo.mark_deleted(context.repo_id, context.deleted_files)
