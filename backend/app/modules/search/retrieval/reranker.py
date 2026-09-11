
"""
app/modules/search/retrieval/reranker.py

Final reranking stage for hybrid retrieval.

The hybrid merger already combines dense and sparse retrieval using
Reciprocal Rank Fusion (RRF). This reranker applies lightweight
code-search-specific signals on top of the RRF ranking.

This is intentionally deterministic and does not claim to be an
ML-based reranker such as Cohere Rerank or Jina Rerank.
"""

from __future__ import annotations
from sentence_transformers import CrossEncoder

import re

from app.modules.search.domain.search_domain import (
    RetrievedChunk,
    SearchContext,
)


class Reranker:
    """Apply deterministic code-search reranking to merged candidates."""

    def rerank(
        self,
        context: SearchContext,
        candidates: list[RetrievedChunk],
        top_k: int = 10,
    ) -> list[RetrievedChunk]:
        """
        Rerank merged retrieval candidates.

        The ResultMerger provides the primary RRF score. This stage adds
        lightweight lexical signals for identifiers explicitly extracted
        during query preprocessing.

        The final reranking score is stored in chunk.score so that the
        API exposes only one score for each retrieved result.
        """

        if top_k <= 0:
            return []

        if not candidates:
            return []

        identifiers = self._normalize_terms(context.identifiers)
        keywords = self._normalize_terms(context.keywords)

        scored_candidates: list[tuple[float, int, RetrievedChunk]] = []

        for original_rank, chunk in enumerate(candidates):
            score = self._calculate_score(
                chunk=chunk,
                identifiers=identifiers,
                keywords=keywords,
            )

            # Store the final reranking score as the single score
            # exposed by the API.
            chunk.score = score

            print(
                f"RERANKER SCORE: {score:.4f} | "
                f"{chunk.file_path}"
            )

            scored_candidates.append(
                (
                    score,
                    original_rank,
                    chunk,
                )
            )

        # Higher reranking score first.
        #
        # original_rank is used as a stable tie-breaker so equally scored
        # candidates retain their RRF ordering.
        scored_candidates.sort(
            key=lambda item: (
                item[0],
                -item[1],
            ),
            reverse=True,
        )

        return [
            chunk
            for _, _, chunk in scored_candidates[:top_k]
        ]

    def _calculate_score(
        self,
        chunk: RetrievedChunk,
        identifiers: list[str],
        keywords: list[str],
    ) -> float:
        """
        Calculate a deterministic reranking score.

        RRF remains the base score. Exact identifier matches receive a
        stronger boost than generic keyword matches because code symbols
        are highly informative for repository search.
        """

        func_name = str(
            chunk.metadata.get("function_name") or ""
        )

        class_name = str(
            chunk.metadata.get("class_name") or ""
        )

        content = (
            f"{func_name} "
            f"{class_name} "
            f"{chunk.content}"
        ).lower()

        score = float(chunk.score)

        identifier_matches = self._count_matches(
            content,
            identifiers,
        )

        keyword_matches = self._count_matches(
            content,
            keywords,
        )

        if identifiers:
            identifier_ratio = (
                identifier_matches / len(identifiers)
            )

            score += identifier_ratio * 0.20

        if keywords:
            keyword_ratio = (
                keyword_matches / len(keywords)
            )

            score += keyword_ratio * 0.05

        return score

    @staticmethod
    def _count_matches(
        content: str,
        terms: list[str],
    ) -> int:
        """Count unique query terms occurring in the chunk."""

        count = 0

        for term in terms:
            if Reranker._term_matches(content, term):
                count += 1

        return count

    @staticmethod
    def _term_matches(
        content: str,
        term: str,
    ) -> bool:
        """
        Check whether a term occurs in the code content.

        Word boundaries are used for identifier-like terms to avoid
        treating `login` as an exact match for `login_user`.
        """

        if not term:
            return False

        pattern = rf"(?<!\w){re.escape(term)}(?!\w)"

        return re.search(
            pattern,
            content,
            flags=re.IGNORECASE,
        ) is not None

    @staticmethod
    def _normalize_terms(
        terms: list[str],
    ) -> list[str]:
        """Normalize and deduplicate search terms."""

        normalized: list[str] = []
        seen: set[str] = set()

        for term in terms:
            if not isinstance(term, str):
                continue

            value = term.strip()

            if not value:
                continue

            key = value.lower()

            if key in seen:
                continue

            seen.add(key)
            normalized.append(value)

        return normalized
