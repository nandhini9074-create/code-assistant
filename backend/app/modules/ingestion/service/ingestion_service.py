"""
app/modules/ingestion/service/ingestion_service.py
Service that orchestrates the ingestion pipeline.
"""

from app.core.enums import IngestionSource
from app.modules.ingestion.domain.ingestion_domain import IngestionContext, PipelineResult
from app.modules.ingestion.pipeline import (
    AstChunkingStage,
    CheckpointUpdateStage,
    ChunkDeduplicationStage,
    ContentFetchStage,
    DeletedChunkCleanupStage,
    EmbeddingGenerationStage,
    FileFilterStage,
    FileHashCheckStage,
    MetadataEnrichmentStage,
    RepositoryFetchStage,
    RequestValidationStage,
    VectorUpsertStage,
)


class IngestionService:
    """Orchestrates the 11-stage ingestion pipeline."""
    
    def __init__(
        self,
        request_validation_stage: RequestValidationStage,
        repository_fetch_stage: RepositoryFetchStage,
        file_filter_stage: FileFilterStage,
        content_fetch_stage: ContentFetchStage,
        file_hash_check_stage: FileHashCheckStage,
        ast_chunking_stage: AstChunkingStage,
        chunk_deduplication_stage: ChunkDeduplicationStage,
        metadata_enrichment_stage: MetadataEnrichmentStage,
        embedding_generation_stage: EmbeddingGenerationStage,
        vector_upsert_stage: VectorUpsertStage,
        deleted_chunk_cleanup_stage: DeletedChunkCleanupStage,
        checkpoint_update_stage: CheckpointUpdateStage,
    ) -> None:
        self.stages = [
            request_validation_stage,
            repository_fetch_stage,
            file_filter_stage,
            content_fetch_stage,
            file_hash_check_stage,
            ast_chunking_stage,
            chunk_deduplication_stage,
            metadata_enrichment_stage,
            embedding_generation_stage,
            vector_upsert_stage,
            deleted_chunk_cleanup_stage,
            checkpoint_update_stage,
        ]

    async def run_pipeline(
        self,
        job_id: str,
        repo_id: str,
        source: IngestionSource,
        commit_sha: str,
        extracted_zip_path: str | None = None,
    ) -> PipelineResult:
        """Executes the ingestion pipeline."""
        context = IngestionContext(
            job_id=job_id,
            repo_id=repo_id,
            source=source,
            commit_sha=commit_sha,
            extracted_zip_path=extracted_zip_path,
        )
        
        try:
            for stage in self.stages:
                await stage.execute(context)
                
            return PipelineResult(
                success=True,
                job_id=job_id,
                processed_files_count=len(context.files),
                indexed_chunks_count=sum(len(f.chunks) for f in context.files),
            )
        except Exception as exc:
            return PipelineResult(
                success=False,
                job_id=job_id,
                error_message=str(exc),
            )
