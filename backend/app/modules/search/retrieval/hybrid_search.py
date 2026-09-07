
"""
app/modules/search/retrieval/hybrid_search.py

Orchestrates dense retrieval, sparse lexical retrieval, result merging,
and final reranking.
"""

from __future__ import annotations

from app.modules.search.domain.search_domain import (
    RetrievedChunk,
    SearchContext,
)
from app.modules.search.retrieval.dense_search import DenseSearch
from app.modules.search.retrieval.reranker import Reranker
from app.modules.search.retrieval.result_merger import ResultMerger
from app.modules.search.retrieval.sparse_search import SparseSearch


class HybridSearch:
    """Combine dense and sparse retrieval strategies."""

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

    async def search(
        self,
        context: SearchContext,
        limit: int = 20,
    ) -> list[RetrievedChunk]:
        """
        Perform hybrid retrieval.

        Retrieval flow:

            DenseSearch
                 +
            SparseSearch
                 ↓
            ResultMerger / RRF
                 ↓
            Reranker
                 ↓
            RetrievedChunk[]
        """

        if context.early_exit:
            return []

        if limit <= 0:
            return []

        dense_candidates = await self.dense.search(
            context,
            limit=limit,
        )

        sparse_candidates = await self.sparse.search(
            context,
            limit=limit,
        )

        # Both retrieval branches may legitimately return no results.
        # The merger decides how to combine the available candidates.
        merged_candidates = self.merger.merge(
            dense_candidates,
            sparse_candidates,
        )

        if not merged_candidates:
            return []

        return self.reranker.rerank(
            context,
            merged_candidates,
            top_k=limit,
        )
