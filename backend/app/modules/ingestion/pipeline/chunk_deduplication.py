"""
app/modules/ingestion/pipeline/chunk_deduplication.py
Pipeline stage: Chunk deduplication.
"""

from app.core.logging import get_logger
from app.modules.ingestion.domain.ingestion_domain import IngestionContext
from app.modules.ingestion.repository.chunk_registry_repo import ChunkRegistryRepository

logger = get_logger(__name__)


class ChunkDeduplicationStage:
    def __init__(self, chunk_repo: ChunkRegistryRepository) -> None:
        self.chunk_repo = chunk_repo

    async def execute(self, context: IngestionContext) -> None:
        """Checks if chunks already exist in the database."""
        total_chunks = sum(len(f.chunks) for f in context.files if f.is_new_or_modified)
        logger.info("stage_7_chunk_deduplication_started", candidate_chunks=total_chunks)
        reused_count = 0
        new_count = 0

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
                    reused_count += 1
                else:
                    chunk.is_new = True
                    new_count += 1

        logger.info(
            "stage_7_chunk_deduplication_completed",
            new_chunks_to_embed=new_count,
            reused_existing_chunks=reused_count,
        )
