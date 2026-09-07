"""
app/modules/ingestion/pipeline/vector_upsert.py
Pipeline stage: Vector upsert to Qdrant.
"""

import uuid

from qdrant_client.http import models as qmodels

from app.core.logging import get_logger
from app.infrastructure.database.models.chunk_registry import ChunkRegistry
from app.infrastructure.qdrant.collection_manager import ensure_collection_exists
from app.infrastructure.qdrant.vector_repository import generate_point_id, upsert_vectors
from app.modules.ingestion.domain.ingestion_domain import IngestionContext
from app.modules.ingestion.repository.chunk_registry_repo import ChunkRegistryRepository
from app.modules.repositories.repository.repository_repo import RepositoryRepository

logger = get_logger(__name__)


class VectorUpsertStage:
    def __init__(
        self,
        repo_repo: RepositoryRepository,
        chunk_repo: ChunkRegistryRepository,
    ) -> None:
        self.repo_repo = repo_repo
        self.chunk_repo = chunk_repo

    async def execute(self, context: IngestionContext) -> None:
        """Upserts new chunks to Qdrant and saves them to PostgreSQL."""
        logger.info("stage_10_vector_upsert_started", repo_id=context.repo_id)
        repo = await self.repo_repo.get_by_id(uuid.UUID(context.repo_id))
        if not repo:
            logger.error("stage_10_vector_upsert_aborted", reason="Repository not found")
            return

        points = []
        db_chunks = []
        
        for file in context.files:
            if not file.is_new_or_modified or not file.chunks:
                continue
                
            for chunk in file.chunks:
                if not chunk.is_new:
                    continue
                    
                # Generate deterministic point ID
                chunk.point_id = generate_point_id(context.repo_id, file.file_path, chunk.chunk_hash)
                
                if chunk.embedding:
                    if len(chunk.embedding) != 1024:
                        logger.error(
                            "stage_10_vector_dimension_mismatch",
                            chunk_hash=chunk.chunk_hash,
                            dimension=len(chunk.embedding),
                            expected=1024,
                        )
                        raise ValueError(
                            f"Vector dimension mismatch for chunk {chunk.chunk_hash}: "
                            f"expected 1024, got {len(chunk.embedding)}"
                        )

                    points.append(qmodels.PointStruct(
                        id=chunk.point_id,
                        vector=chunk.embedding,
                        payload=chunk.metadata,
                    ))
                    
                db_chunks.append(
                    ChunkRegistry(
                        repo_id=uuid.UUID(context.repo_id),
                        file_path=file.file_path,
                        chunk_hash=chunk.chunk_hash,
                        symbol_name=chunk.function_name or chunk.class_name,
                        symbol_type=chunk.chunk_type,
                        start_line=chunk.start_line,
                        end_line=chunk.end_line,
                        qdrant_point_id=chunk.point_id,
                        last_seen_job_id=uuid.UUID(context.job_id) if context.job_id else None,
                    )
                )

        if points:
            logger.info("stage_10_upserting_to_qdrant", points_count=len(points), collection=repo.qdrant_collection_name)
            await ensure_collection_exists(repo.qdrant_collection_name)
            await upsert_vectors(repo.qdrant_collection_name, points)
            logger.info("stage_10_qdrant_upsert_success", points_count=len(points))
            
        if db_chunks:
            # Delete old chunks for these modified files first
            modified_files = [f.file_path for f in context.files if f.is_new_or_modified]
            if modified_files:
                logger.info("stage_10_cleaning_old_db_chunks", modified_files_count=len(modified_files))
                await self.chunk_repo.delete_by_file_paths(uuid.UUID(context.repo_id), modified_files)
                
            logger.info("stage_10_saving_to_postgresql", db_chunks_count=len(db_chunks))
            await self.chunk_repo.bulk_create(db_chunks)
            logger.info("stage_10_postgresql_save_success", db_chunks_count=len(db_chunks))
