"""
app/modules/search/retrieval/hybrid_search.py
Orchestrates dense + sparse + merge + rerank.
"""

from app.modules.search.domain.search_domain import RetrievedChunk, SearchContext
from app.modules.search.retrieval.dense_search import DenseSearch
from app.modules.search.retrieval.reranker import Reranker
from app.modules.search.retrieval.result_merger import ResultMerger
from app.modules.search.retrieval.sparse_search import SparseSearch


class HybridSearch:
    """Combines different search strategies."""
    
    def __init__(
        self,
        dense: DenseSearch,
        sparse: SparseSearch,
        merger: ResultMerger,
        reranker: Reranker,
    ) -> None:
        self.dense = dense
        self.sparse = sparse
        self.merger = merger
        self.reranker = reranker

    async def search(self, context: SearchContext, limit: int = 20) -> list[RetrievedChunk]:
        """Perform hybrid search."""
        dense_candidates = await self.dense.search(context, limit=limit)
        sparse_candidates = await self.sparse.search(context, limit=limit)
        
        merged = self.merger.merge(dense_candidates, sparse_candidates)
        return self.reranker.rerank(context, merged, top_k=limit)
