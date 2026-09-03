"""
app/modules/search/retrieval/reranker.py
Re-ranks merged results.
"""

from app.modules.search.domain.search_domain import RetrievedChunk, SearchContext


class Reranker:
    """Re-orders candidates."""
    
    def rerank(self, context: SearchContext, candidates: list[RetrievedChunk], top_k: int = 10) -> list[RetrievedChunk]:
        """
        In a real implementation, this might call Cohere Rerank or Voyage Rerank.
        Here we just sort by the combined score.
        """
        # Sort descending by score
        candidates.sort(key=lambda x: x.score, reverse=True)
        return candidates[:top_k]
