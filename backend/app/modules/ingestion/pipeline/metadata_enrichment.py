"""
app/modules/ingestion/pipeline/metadata_enrichment.py
Pipeline stage: Metadata enrichment.
"""

from app.core.logging import get_logger
from app.modules.ingestion.domain.ingestion_domain import IngestionContext
from app.shared.utils.file_utils import get_language_from_extension

logger = get_logger(__name__)


class MetadataEnrichmentStage:
    async def execute(self, context: IngestionContext) -> None:
        """Enriches chunks with repository and file level context."""
        logger.info("stage_8_metadata_enrichment_started")
        enriched_count = 0

        for file in context.files:
            if not file.is_new_or_modified or not file.chunks:
                continue
                
            language = get_language_from_extension(file.file_path) or "unknown"
            
            for chunk in file.chunks:
                if not chunk.is_new:
                    continue
                    
                chunk.metadata.update({
                    "repo_name": context.repo_name,
                    "repo_id": context.repo_id,
                    "file_path": file.file_path,
                    "commit_sha": context.commit_sha,
                    "function_name": chunk.function_name,
                    "class_name": chunk.class_name,
                    "language": language,
                    "chunk_type": chunk.chunk_type,
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    "file_hash": file.file_hash,
                    "code": chunk.code,
                    "docstring": chunk.docstring,
                    "chunk_hash": chunk.chunk_hash,
                })
                enriched_count += 1

        logger.info("stage_8_metadata_enrichment_completed", enriched_chunks_count=enriched_count)
