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

        print("\n========== HYBRID SEARCH START ==========")
        print("REPO ID:", context.repo_id)
        print("COLLECTION:", context.qdrant_collection)
        print("QUERY VECTOR EXISTS:", bool(context.query_vector))
        print(
            "QUERY VECTOR DIMENSION:",
            len(context.query_vector)
            if context.query_vector
            else 0,
        )

        # ---------------------------------------------------------
        # Early exit
        # ---------------------------------------------------------

        if context.early_exit:
            print("HYBRID SEARCH: EARLY EXIT ALREADY SET")
            return []

        if limit <= 0:
            print("HYBRID SEARCH: INVALID LIMIT")
            return []

        # ---------------------------------------------------------
        # Dense retrieval
        # ---------------------------------------------------------

        print("HYBRID SEARCH: CALLING DENSE SEARCH")

        dense_candidates = await self.dense.search(
            context,
            limit=limit,
        )

        print(
            "HYBRID SEARCH: DENSE RESULTS:",
            len(dense_candidates),
        )

        # ---------------------------------------------------------
        # Sparse retrieval
        # ---------------------------------------------------------

        print("HYBRID SEARCH: CALLING SPARSE SEARCH")

        sparse_candidates = await self.sparse.search(
            context,
            limit=limit,
        )

        print(
            "HYBRID SEARCH: SPARSE RESULTS:",
            len(sparse_candidates),
        )

        # ---------------------------------------------------------
        # Merge
        # ---------------------------------------------------------

        print("HYBRID SEARCH: MERGING RESULTS")

        merged_candidates = self.merger.merge(
            dense_candidates,
            sparse_candidates,
        )

        print(
            "HYBRID SEARCH: MERGED RESULTS:",
            len(merged_candidates),
        )

        if not merged_candidates:
            print("HYBRID SEARCH: NO MERGED RESULTS")
            return []

        # ---------------------------------------------------------
        # Reranking
        # ---------------------------------------------------------

        print("HYBRID SEARCH: CALLING RERANKER")

        results = self.reranker.rerank(
            context,
            merged_candidates,
            top_k=limit,
        )

        print(
            "HYBRID SEARCH: RERANKED RESULTS:",
            len(results),
        )

        print("========== HYBRID SEARCH END ==========\n")

        return results