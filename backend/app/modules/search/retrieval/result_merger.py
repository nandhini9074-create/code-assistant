
"""
app/modules/search/retrieval/result_merger.py

Merges and deduplicates results from dense and sparse retrieval.

Uses Reciprocal Rank Fusion (RRF) so that dense cosine scores and sparse
lexical scores do not need to be on the same numerical scale.
"""

from __future__ import annotations

from app.modules.search.domain.search_domain import RetrievedChunk


class ResultMerger:
    """Merge dense and sparse candidates using Reciprocal Rank Fusion."""

    def __init__(
        self,
        rrf_k: int = 60,
    ) -> None:
        """
        Args:
            rrf_k: RRF smoothing constant. A value of 60 is a common
                default and prevents top-ranked results from dominating
                too aggressively.
        """
        if rrf_k <= 0:
            raise ValueError("rrf_k must be greater than zero")

        self.rrf_k = rrf_k

    def merge(
        self,
        dense_results: list[RetrievedChunk],
        sparse_results: list[RetrievedChunk],
    ) -> list[RetrievedChunk]:
        """
        Merge dense and sparse results using Reciprocal Rank Fusion.

        Each result contributes:

            1 / (rrf_k + rank)

        to its final RRF score.

        Results appearing in both retrieval lists receive contributions
        from both rankings.

        The original retrieval score is preserved in metadata and the
        RetrievedChunk score is replaced by the RRF score for downstream
        reranking.
        """

        if not dense_results and not sparse_results:
            return []

        candidates: dict[str, RetrievedChunk] = {}
        rrf_scores: dict[str, float] = {}

        self._add_ranked_results(
            results=dense_results,
            candidates=candidates,
            rrf_scores=rrf_scores,
        )

        self._add_ranked_results(
            results=sparse_results,
            candidates=candidates,
            rrf_scores=rrf_scores,
        )

        merged: list[RetrievedChunk] = []

        for key, chunk in candidates.items():
            chunk.score = rrf_scores[key]
            merged.append(chunk)

        merged.sort(
            key=lambda chunk: chunk.score,
            reverse=True,
        )

        return merged

    def _add_ranked_results(
        self,
        results: list[RetrievedChunk],
        candidates: dict[str, RetrievedChunk],
        rrf_scores: dict[str, float],
    ) -> None:
        """Add one ranked result list to the RRF calculation."""

        for rank, chunk in enumerate(results, start=1):
            key = self._deduplication_key(chunk)

            # Calculate this source's RRF contribution.
            contribution = 1.0 / (self.rrf_k + rank)

            rrf_scores[key] = (
                rrf_scores.get(key, 0.0) + contribution
            )

            # Keep the first complete chunk representation.
            # Dense results are processed first, so if a chunk appears
            # in both sources, the dense representation is retained.
            if key not in candidates:
                candidates[key] = chunk

    @staticmethod
    def _deduplication_key(chunk: RetrievedChunk) -> str:
        """
        Build a stable key for identifying the same retrieved chunk.

        chunk_hash is preferred because it identifies the indexed chunk.
        file_path is included to avoid accidental collisions between
        repositories or indexing schemes where hashes are not globally
        unique.
        """

        if chunk.chunk_hash:
            return f"{chunk.file_path}:{chunk.chunk_hash}"

        return (
            f"{chunk.file_path}:"
            f"{chunk.metadata.get('start_line', '')}:"
            f"{chunk.metadata.get('end_line', '')}:"
            f"{chunk.content}"
        )

