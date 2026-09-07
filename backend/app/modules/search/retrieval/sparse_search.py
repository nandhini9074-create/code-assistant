
"""
app/modules/search/retrieval/sparse_search.py

Sparse lexical retrieval using Qdrant payload text matching.

This implementation uses Qdrant MatchText conditions against the indexed
`content` payload. It retrieves chunks containing one or more important
keywords/identifiers extracted during query preprocessing.

This is lexical retrieval, not BM25. Relevance is estimated using the
number of query terms found in each retrieved chunk.

The repository is isolated using the `repo_id` payload filter.
"""

from __future__ import annotations

from qdrant_client.http import models as qmodels

from app.core.logging import get_logger
from app.infrastructure.qdrant.client import get_qdrant_client
from app.modules.search.domain.search_domain import (
    RetrievedChunk,
    SearchContext,
)

logger = get_logger(__name__)


class SparseSearch:
    """Perform sparse lexical retrieval using Qdrant payload matching."""

    _MAX_TERMS = 10

    async def search(
        self,
        context: SearchContext,
        limit: int = 20,
    ) -> list[RetrievedChunk]:
        """
        Retrieve chunks containing important query terms.

        The search uses:
        - context.identifiers
        - context.keywords
        - Qdrant MatchText
        - repo_id filtering

        Returns an empty list when lexical retrieval cannot be performed.
        """

        if context.early_exit:
            return []

        if limit <= 0:
            return []

        if not context.qdrant_collection:
            return []

        if not context.repo_id:
            return []

        terms = self._build_terms(context)

        if not terms:
            logger.info(
                "sparse_search_skipped_no_terms",
                repo_id=context.repo_id,
            )
            return []

        should_conditions: list[qmodels.Condition] = [
            qmodels.FieldCondition(
                key="content",
                match=qmodels.MatchText(text=term),
            )
            for term in terms
        ]

        search_filter = qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="repo_id",
                    match=qmodels.MatchValue(
                        value=context.repo_id
                    ),
                )
            ],
            should=should_conditions,
            min_should=1,
        )

        try:
            client = get_qdrant_client()

            points, _ = await client.scroll(
                collection_name=context.qdrant_collection,
                scroll_filter=search_filter,
                limit=limit,
                with_payload=True,
                with_vectors=False,
            )

        except Exception:
            logger.exception(
                "sparse_search_failed",
                repo_id=context.repo_id,
                collection=context.qdrant_collection,
            )
            return []

        chunks: list[RetrievedChunk] = []

        for point in points or []:
            payload = point.payload or {}

            content = payload.get("content", "")

            if not isinstance(content, str):
                content = str(content)

            chunks.append(
                RetrievedChunk(
                    chunk_hash=payload.get(
                        "chunk_hash",
                        str(point.id),
                    ),
                    file_path=payload.get("file_path", ""),
                    content=content,
                    score=_term_overlap_score(
                        content,
                        terms,
                    ),
                    metadata=payload,
                )
            )

        # Qdrant scroll does not provide a relevance ranking.
        # Sort explicitly using our lexical overlap score.
        chunks.sort(
            key=lambda chunk: chunk.score,
            reverse=True,
        )

        logger.info(
            "sparse_search_complete",
            hits=len(chunks),
            terms=len(terms),
            repo_id=context.repo_id,
        )

        return chunks

    def _build_terms(
        self,
        context: SearchContext,
    ) -> list[str]:
        """
        Build a unique list of identifiers and keywords.

        Identifiers are placed first because exact code symbols such as
        function/class/variable names are generally more valuable for
        repository code search than generic keywords.
        """

        raw_terms = context.identifiers + context.keywords

        terms: list[str] = []
        seen: set[str] = set()

        for term in raw_terms:
            if not isinstance(term, str):
                continue

            normalized = term.strip()

            if not normalized:
                continue

            key = normalized.lower()

            if key in seen:
                continue

            seen.add(key)
            terms.append(normalized)

            if len(terms) >= self._MAX_TERMS:
                break

        return terms


def _term_overlap_score(
    content: str,
    terms: list[str],
) -> float:
    """
    Calculate a simple lexical overlap score in the range [0, 1].

    This is NOT BM25. It is only used to rank the chunks returned by
    Qdrant's MatchText filtering before hybrid result merging.
    """

    if not content or not terms:
        return 0.0

    lower_content = content.lower()

    matched_terms = sum(
        1
        for term in terms
        if term.lower() in lower_content
    )

    return matched_terms / len(terms)

