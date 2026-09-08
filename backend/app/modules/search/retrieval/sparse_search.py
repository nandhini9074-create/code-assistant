"""
app/modules/search/retrieval/sparse_search.py

Sparse lexical retrieval using Qdrant payload fields.

Search priority:
    1. function_name
    2. class_name
    3. code

The current architecture uses multiple Qdrant collections.
Each repository has its own collection following:

    repo_owner_repositoryname

Global search searches all repository collections.

PostgreSQL is not used.
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
    """Perform sparse lexical retrieval across repository Qdrant collections."""

    _MAX_TERMS = 10

    async def search(
        self,
        context: SearchContext,
        limit: int = 20,
    ) -> list[RetrievedChunk]:

        if context.early_exit:
            print("SPARSE SEARCH: Early exit already set")
            return []

        if limit <= 0:
            print("SPARSE SEARCH: Invalid limit")
            return []

        try:
            terms = self._build_terms(context)

            if not terms:
                logger.info(
                    "sparse_search_skipped_no_terms",
                    repo_name=context.repo_name,
                )
                print("SPARSE SEARCH: No search terms found")
                return []

            print("\n========== SPARSE SEARCH DEBUG ==========")
            print("QDRANT SEARCH MODE:", context.qdrant_collection or "ALL REPOSITORY COLLECTIONS")
            print("REQUEST REPOSITORY NAME:", context.repo_name)
            print("SEARCH TERMS:", terms)
            print("SEARCH PRIORITY: function_name > class_name > code")
            print("LIMIT:", limit)
            print("=========================================\n")

            client = get_qdrant_client()

            if context.qdrant_collection:
                collections = [context.qdrant_collection]
            else:
                collections_response = await client.get_collections()
                collections = [
                    collection.name
                    for collection in collections_response.collections
                    if collection.name.startswith("repo_")
                ]

            print(
                f"SPARSE SEARCH: Found "
                f"{len(collections)} repository Qdrant collections"
            )

            if not collections:
                print("SPARSE SEARCH: No repository Qdrant collections found")
                return []

            chunks: list[RetrievedChunk] = []

            for collection_name in collections:

                print(
                    f"\nSPARSE SEARCH: Searching collection "
                    f"'{collection_name}'..."
                )

                conditions: list[qmodels.Condition] = []

                for term in terms:
                    # Function name
                    conditions.append(
                        qmodels.FieldCondition(
                            key="function_name",
                            match=qmodels.MatchText(
                                text=term,
                            ),
                        )
                    )

                    # Class name
                    conditions.append(
                        qmodels.FieldCondition(
                            key="class_name",
                            match=qmodels.MatchText(
                                text=term,
                            ),
                        )
                    )

                    # Source code fallback
                    conditions.append(
                        qmodels.FieldCondition(
                            key="code",
                            match=qmodels.MatchText(
                                text=term,
                            ),
                        )
                    )

                search_filter = qmodels.Filter(
                    should=conditions,
                    min_should=qmodels.MinShould(
                        min_count=1,
                        conditions=conditions,
                    ),
                )

                try:
                    points, _ = await client.scroll(
                        collection_name=collection_name,
                        scroll_filter=search_filter,
                        limit=limit,
                        with_payload=True,
                        with_vectors=False,
                    )
                except Exception as coll_exc:
                    logger.warning(
                        "sparse_search_collection_failed",
                        collection=collection_name,
                        error=str(coll_exc),
                    )
                    print(
                        f"SPARSE SEARCH: Failed collection "
                        f"'{collection_name}', skipping: {coll_exc}"
                    )
                    continue

                print(
                    f"SPARSE SEARCH: Collection "
                    f"'{collection_name}' returned "
                    f"{len(points or [])} points"
                )

                for point in points or []:

                    payload = point.payload or {}

                    function_name = payload.get(
                        "function_name",
                        "",
                    )

                    class_name = payload.get(
                        "class_name",
                        "",
                    )

                    code = (
                        payload.get("code")
                        or payload.get("content")
                        or ""
                    )

                    if not isinstance(function_name, str):
                        function_name = str(function_name)

                    if not isinstance(class_name, str):
                        class_name = str(class_name)

                    if not isinstance(code, str):
                        code = str(code)

                    # ---------------------------------------------------
                    # Calculate weighted lexical score.
                    #
                    # Function name match = strongest
                    # Class name match    = second strongest
                    # Code match           = fallback
                    # ---------------------------------------------------

                    score = _weighted_lexical_score(
                        function_name=function_name,
                        class_name=class_name,
                        code=code,
                        terms=terms,
                    )

                    metadata = dict(payload)

                    # Preserve the originating Qdrant collection.
                    metadata["_qdrant_collection"] = collection_name

                    chunks.append(
                        RetrievedChunk(
                            chunk_hash=payload.get(
                                "chunk_hash",
                                str(point.id),
                            ),
                            file_path=(
                                payload.get("file_path")
                                or payload.get("source")
                                or ""
                            ),
                            content=code,
                            score=score,
                            metadata=metadata,
                        )
                    )

            # -----------------------------------------------------------
            # Remove duplicate chunks.
            # -----------------------------------------------------------

            chunks = self._deduplicate_chunks(chunks)

            # -----------------------------------------------------------
            # Global ranking.
            # -----------------------------------------------------------

            chunks.sort(
                key=lambda chunk: chunk.score,
                reverse=True,
            )

            chunks = chunks[:limit]

            print(
                f"\nSPARSE SEARCH: Retrieved "
                f"{len(chunks)} global chunks"
            )

            for index, chunk in enumerate(
                chunks[:10],
                start=1,
            ):

                print(f"\n--- Sparse Result {index} ---")

                print(
                    "Collection:",
                    chunk.metadata.get(
                        "_qdrant_collection",
                        "",
                    ),
                )

                print(
                    "Repository:",
                    chunk.metadata.get(
                        "repo_name",
                        "",
                    ),
                )

                print(
                    "Function:",
                    chunk.metadata.get(
                        "function_name",
                        "",
                    ),
                )

                print(
                    "Class:",
                    chunk.metadata.get(
                        "class_name",
                        "",
                    ),
                )

                print(
                    "File:",
                    chunk.file_path,
                )

                print(
                    "Score:",
                    chunk.score,
                )

                print(
                    "Chunk Hash:",
                    chunk.chunk_hash,
                )

                print(
                    "Code:",
                    chunk.content[:500],
                )

            logger.info(
                "sparse_search_complete",
                hits=len(chunks),
                terms=len(terms),
                collections=len(collections),
                repo_name=context.repo_name,
            )

            return chunks
        except Exception as exc:
            logger.warning(
                "sparse_search_failed_continuing_with_dense",
                error=str(exc),
            )
            print("SPARSE SEARCH FAILED — CONTINUING WITH DENSE RESULTS")
            return []

    def _build_terms(
        self,
        context: SearchContext,
    ) -> list[str]:
        """
        Build a unique list of identifiers and keywords.

        Identifiers are preferred because code symbols are usually
        more useful than generic natural-language words.
        """

        raw_terms = (
            (context.identifiers or [])
            + (context.keywords or [])
        )

        if not raw_terms and context.query:
            raw_terms = [
                word.strip()
                for word in context.query.split()
                if len(word.strip()) > 2
            ]

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

    @staticmethod
    def _deduplicate_chunks(
        chunks: list[RetrievedChunk],
    ) -> list[RetrievedChunk]:
        """
        Remove duplicate chunks.

        Preferred identity:
            chunk_hash

        Fallback identity:
            collection + file_path + content

        Highest-scoring copy is retained.
        """

        unique_chunks: dict[str, RetrievedChunk] = {}

        for chunk in chunks:

            collection = str(
                chunk.metadata.get(
                    "_qdrant_collection",
                    "",
                )
            )

            chunk_hash = str(
                chunk.chunk_hash or "",
            )

            if chunk_hash:
                key = f"hash:{chunk_hash}"
            else:
                key = (
                    f"fallback:"
                    f"{collection}:"
                    f"{chunk.file_path}:"
                    f"{chunk.content}"
                )

            existing = unique_chunks.get(key)

            if existing is None:
                unique_chunks[key] = chunk
                continue

            if chunk.score > existing.score:
                unique_chunks[key] = chunk

        return list(unique_chunks.values())


def _weighted_lexical_score(
    function_name: str,
    class_name: str,
    code: str,
    terms: list[str],
) -> float:
    """
    Calculate a weighted lexical relevance score.

    Priority:

        function_name -> 1.0
        class_name    -> 0.8
        code          -> 0.4

    The score is normalized by the number of query terms.

    This is NOT BM25.
    """

    if not terms:
        return 0.0

    function_lower = function_name.lower()
    class_lower = class_name.lower()
    code_lower = code.lower()

    total_score = 0.0

    for term in terms:

        term_lower = term.lower()

        # Strongest signal:
        # exact/lexical match in function name.
        if term_lower in function_lower:
            total_score += 1.0

        # Second strongest signal:
        # match in class name.
        elif term_lower in class_lower:
            total_score += 0.8

        # Fallback:
        # match anywhere in source code.
        elif term_lower in code_lower:
            total_score += 0.4

    return total_score / len(terms)