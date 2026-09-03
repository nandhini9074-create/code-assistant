"""
app/modules/search/retrieval/sparse_search.py
Sparse search using exact/keyword matching.
"""

from app.modules.search.domain.search_domain import RetrievedChunk, SearchContext


class SparseSearch:
    """Performs sparse keyword matching."""
    
    async def search(self, context: SearchContext, limit: int = 20) -> list[RetrievedChunk]:
        """
        In a real implementation, this would use a BM25 index,
        Qdrant full-text features, or PostgreSQL tsvector.
        Stubbed for the reference architecture.
        """
        # We simulate finding chunks based on context.identifiers and context.keywords
        return []
