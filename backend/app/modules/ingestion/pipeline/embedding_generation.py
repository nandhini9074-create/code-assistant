"""
app/modules/ingestion/pipeline/embedding_generation.py
Pipeline stage: Embedding generation.
"""

from app.modules.embedding.service.embedding_service import generate_embeddings
from app.modules.ingestion.domain.ingestion_domain import IngestionContext


class EmbeddingGenerationStage:
    async def execute(self, context: IngestionContext) -> None:
        """Generates embeddings for new chunks."""
        new_chunks = []
        
        # Collect all new chunks across all files
        for file in context.files:
            if not file.is_new_or_modified or not file.chunks:
                continue
                
            for chunk in file.chunks:
                if chunk.is_new:
                    new_chunks.append(chunk)
                    
        if not new_chunks:
            return
            
        # Extract text for embedding
        texts = [chunk.content for chunk in new_chunks]
        
        # Generate embeddings
        embeddings = await generate_embeddings(texts=texts, input_type="document")
        
        # Assign embeddings back to the chunks
        for chunk, embedding in zip(new_chunks, embeddings):
            chunk.embedding = embedding
