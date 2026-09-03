"""
app/modules/ingestion/pipeline/chunk_deduplication.py
Pipeline stage: Chunk deduplication.
"""

from app.modules.ingestion.domain.ingestion_domain import IngestionContext
from app.modules.ingestion.repository.chunk_registry_repo import ChunkRegistryRepository


class ChunkDeduplicationStage:
    def __init__(self, chunk_repo: ChunkRegistryRepository) -> None:
        self.chunk_repo = chunk_repo

    async def execute(self, context: IngestionContext) -> None:
        """Checks if chunks already exist in the database."""
        for file in context.files:
            if not file.is_new_or_modified or not file.chunks:
                continue
                
            existing_chunks = await self.chunk_repo.get_by_file_path(context.repo_id, file.file_path)
            existing_hashes = {c.chunk_hash: c for c in existing_chunks}
            
            for chunk in file.chunks:
                existing = existing_hashes.get(chunk.chunk_hash)
                if existing:
                    chunk.is_new = False
                    chunk.point_id = existing.point_id
                else:
                    chunk.is_new = True
