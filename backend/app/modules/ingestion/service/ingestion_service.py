"""
app/modules/ingestion/service/ingestion_service.py
Service that orchestrates the ingestion pipeline.
"""

from app.core.enums import TriggerSource
from app.core.logging import get_logger
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

logger = get_logger(__name__)


class IngestionService:
    """Orchestrates the 12-stage ingestion pipeline."""
    
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
        repo_name: str,
        source: TriggerSource,
        commit_sha: str,
        extracted_zip_path: str | None = None,
        github_token: str | None = None,
        full_reindex: bool = False,
        webhook_diff: dict[str, list[str]] | None = None,
    ) -> PipelineResult:
        """Executes the ingestion pipeline."""
        logger.info(
            "pipeline_started",
            job_id=job_id,
            repo_id=repo_id,
            repo_name=repo_name,
            source=source.value if hasattr(source, "value") else str(source),
            commit_sha=commit_sha,
            full_reindex=full_reindex,
        )
        context = IngestionContext(
            job_id=job_id,
            repo_id=repo_id,
            repo_name=repo_name,
            source=source,
            commit_sha=commit_sha,
            extracted_zip_path=extracted_zip_path,
            github_token=github_token,
            full_reindex=full_reindex,
            webhook_diff=webhook_diff,
        )
        
        try:
            total_stages = len(self.stages)
            for idx, stage in enumerate(self.stages, 1):
                stage_name = stage.__class__.__name__
                logger.info("pipeline_stage_executing", stage_number=f"{idx}/{total_stages}", stage_name=stage_name, job_id=job_id)
                await stage.execute(context)
                logger.info("pipeline_stage_completed", stage_number=f"{idx}/{total_stages}", stage_name=stage_name, job_id=job_id)
                
            failed_files_count = len(context.failed_files)
            successful_file_records = [f for f in context.files if getattr(f.fetch_status, "value", f.fetch_status) == "success"] if context.files else []
            successful_files = len(successful_file_records)
            processed_file_paths = [f.file_path for f in successful_file_records]
            indexed_chunks = sum(len(f.chunks) for f in context.files)
            chunk_ids = [chunk.point_id for f in context.files for chunk in f.chunks if chunk.point_id]

            logger.info(
                "pipeline_completed_successfully",
                job_id=job_id,
                repo_name=repo_name,
                processed_files=successful_files,
                processed_file_paths=processed_file_paths,
                failed_files=failed_files_count,
                indexed_chunks=indexed_chunks,
                chunk_ids=chunk_ids,
                deleted_files=len(context.deleted_files),
            )
            return PipelineResult(
                success=True,
                job_id=job_id,
                processed_files_count=successful_files,
                indexed_chunks_count=indexed_chunks,
                chunk_ids=chunk_ids,
                processed_file_paths=processed_file_paths,
                failed_files_count=failed_files_count,
            )
        except Exception as exc:
            logger.error("pipeline_execution_failed", job_id=job_id, error=str(exc), exc_info=exc)
            return PipelineResult(
                success=False,
                job_id=job_id,
                error_message=str(exc),
            )
