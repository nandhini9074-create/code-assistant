"""
app/modules/ingestion/pipeline/metadata_enrichment.py
Pipeline stage: Metadata enrichment.
"""

from app.modules.ingestion.domain.ingestion_domain import IngestionContext
from app.shared.utils.file_utils import get_language_from_extension


class MetadataEnrichmentStage:
    async def execute(self, context: IngestionContext) -> None:
        """Enriches chunks with repository and file level context."""
        for file in context.files:
            if not file.is_new_or_modified or not file.chunks:
                continue
                
            language = get_language_from_extension(file.file_path) or "unknown"
            
            for chunk in file.chunks:
                if not chunk.is_new:
                    continue
                    
                chunk.metadata.update({
                    "repo_id": str(context.repo_id),
                    "file_path": file.file_path,
                    "language": language,
                    "commit_sha": context.commit_sha,
                })
