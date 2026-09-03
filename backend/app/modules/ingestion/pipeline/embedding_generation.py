"""
app/modules/ingestion/pipeline/embedding_generation.py
Pipeline stage: Embedding generation.
"""

from app.modules.ingestion.domain.ingestion_domain import IngestionContext


class EmbeddingGenerationStage:
    async def execute(self, context: IngestionContext) -> None:
        """Generates embeddings for new chunks."""
        # This is a stub. In a real system, we'd batch chunks and call Voyage AI.
        # We would use with_retry here.
        for file in context.files:
            if not file.is_new_or_modified or not file.chunks:
                continue
                
            for chunk in file.chunks:
                if not chunk.is_new:
                    continue
                    
                # Mock embedding
                chunk.embedding = [0.0] * 1024
