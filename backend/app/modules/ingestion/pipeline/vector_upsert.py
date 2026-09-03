"""
app/modules/ingestion/pipeline/vector_upsert.py
Pipeline stage: Vector upsert to Qdrant.
"""

from qdrant_client.http import models as qmodels

from app.infrastructure.database.models.chunk_registry import ChunkRegistry
from app.infrastructure.qdrant.vector_repository import generate_point_id, upsert_vectors
from app.modules.ingestion.domain.ingestion_domain import IngestionContext
from app.modules.ingestion.repository.chunk_registry_repo import ChunkRegistryRepository
from app.modules.repositories.repository.repository_repo import RepositoryRepository


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
        repo = await self.repo_repo.get_by_id(context.repo_id)
        if not repo:
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
                chunk.point_id = generate_point_id(str(context.repo_id), file.file_path, chunk.chunk_hash)
                
                if chunk.embedding:
                    points.append(qmodels.PointStruct(
                        id=chunk.point_id,
                        vector=chunk.embedding,
                        payload=chunk.metadata,
                    ))
                    
                db_chunks.append(
                    ChunkRegistry(
                        repo_id=context.repo_id,
                        file_path=file.file_path,
                        chunk_hash=chunk.chunk_hash,
                        point_id=chunk.point_id,
                        metadata_json=chunk.metadata,
                        commit_sha=context.commit_sha,
                    )
                )

        if points:
            await upsert_vectors(repo.qdrant_collection, points)
            
        if db_chunks:
            # Delete old chunks for these modified files first
            modified_files = [f.file_path for f in context.files if f.is_new_or_modified]
            if modified_files:
                await self.chunk_repo.delete_by_file_paths(context.repo_id, modified_files)
                
            await self.chunk_repo.bulk_create(db_chunks)
