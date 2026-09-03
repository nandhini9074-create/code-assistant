"""
app/modules/search/retrieval/dense_search.py
Dense vector search using Voyage embeddings and Qdrant.
"""

from app.infrastructure.qdrant.vector_repository import search_vectors
from app.modules.search.domain.search_domain import RetrievedChunk, SearchContext


class DenseSearch:
    """Performs dense vector retrieval."""
    
    async def search(self, context: SearchContext, limit: int = 20) -> list[RetrievedChunk]:
        """
        Embed the query and retrieve similar chunks from Qdrant.
        """
        if not context.qdrant_collection or not context.query_vector:
            return []
            
        # Call Qdrant search vectors abstraction
        scored_points = await search_vectors(
            collection_name=context.qdrant_collection,
            query_vector=context.query_vector,
            limit=limit,
            repo_id=context.repo_id,
        )
        
        chunks = []
        for point in scored_points:
            chunks.append(
                RetrievedChunk(
                    chunk_hash=point.payload.get("chunk_hash", ""),
                    file_path=point.payload.get("file_path", ""),
                    content=point.payload.get("content", ""),
                    score=point.score,
                    metadata=point.payload,
                )
            )
            
        return chunks
