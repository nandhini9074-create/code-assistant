
"""
app/modules/search/retrieval/sparse_search.py

Application-side lexical retrieval using BM25 over existing Qdrant payloads.

Why scroll() instead of query_points(using="sparse"):

    Existing Qdrant collections contain only the default dense vector.
    No named sparse vector was written during ingestion.

Approach:

    1. Page through the selected Qdrant collection using scroll().
    2. Deduplicate points/chunks.
    3. Build code-aware tokens from:
         - function_name
         - class_name
         - code
    4. Calculate corpus-based BM25 IDF.
    5. Score every unique chunk using weighted BM25:
         function_name -> 4.0
         class_name    -> 3.0
         code          -> 1.0
    6. Return top-k RetrievedChunk objects.

No ingestion changes.
No Qdrant payload indexes.
No Qdrant sparse vectors.
No PostgreSQL.

The returned RetrievedChunk objects remain compatible with:

    SparseSearch
        -> ResultMerger
        -> Reranker
        -> ContextBuilder
        -> LLM
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from app.core.logging import get_logger
from app.infrastructure.qdrant.client import get_qdrant_client
from app.modules.search.domain.search_domain import (
    RetrievedChunk,
    SearchContext,
)

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Tunable constants
# ---------------------------------------------------------------------------

_SCROLL_PAGE_SIZE = 500
_MAX_SCROLL_PAGES = 10

_MAX_TERMS = 12

_BM25_K1 = 1.5
_BM25_B = 0.75

_WEIGHT_FUNCTION_NAME = 4.0
_WEIGHT_CLASS_NAME = 3.0
_WEIGHT_CODE = 1.0

# Prevent extremely large source files from dominating the lexical score.
_MAX_CODE_CHARS = 12000


# ---------------------------------------------------------------------------
# Internal BM25 representation
# ---------------------------------------------------------------------------


@dataclass
class _IndexedChunk:
    """One unique Qdrant chunk represented in the BM25 index."""

    point_id: str
    payload: dict[str, Any]

    function_tokens: list[str]
    class_tokens: list[str]
    code_tokens: list[str]

    chunk: RetrievedChunk


# ---------------------------------------------------------------------------
# Sparse search
# ---------------------------------------------------------------------------


class SparseSearch:
    """Perform application-side BM25 retrieval from one Qdrant collection."""

    async def search(
        self,
        context: SearchContext,
        limit: int = 20,
    ) -> list[RetrievedChunk]:
        """Fetch the selected collection and return top BM25 chunks."""

        if context.early_exit:
            print("SPARSE SEARCH: Early exit already set")
            return []

        if limit <= 0:
            print("SPARSE SEARCH: Invalid limit")
            return []

        collection_name = context.qdrant_collection

        if not collection_name:
            print("SPARSE SEARCH: No collection selected")
            return []

        query_terms = _build_terms(context)

        if not query_terms:
            logger.info(
                "sparse_search_skipped_no_terms",
                repo_name=context.repo_name,
            )
            print("SPARSE SEARCH: No search terms found")
            return []

        print("\n========== SPARSE SEARCH (LEXICAL BM25) ==========")
        print("REPO:", context.repo_name)
        print("COLLECTION:", collection_name)
        print("QUERY TERMS:", query_terms)
        print("LIMIT:", limit)
        print("==================================================\n")

        try:
            client = get_qdrant_client()

            # ---------------------------------------------------------------
            # Step 1: Fetch the complete selected collection with pagination.
            # ---------------------------------------------------------------

            points_by_identity: dict[str, tuple[str, dict[str, Any]]] = {}

            offset = None
            pages_fetched = 0

            while pages_fetched < _MAX_SCROLL_PAGES:
                scroll_kwargs: dict[str, Any] = {
                    "collection_name": collection_name,
                    "limit": _SCROLL_PAGE_SIZE,
                    "with_payload": True,
                    "with_vectors": False,
                }

                if offset is not None:
                    scroll_kwargs["offset"] = offset

                points, next_offset = await client.scroll(**scroll_kwargs)

                if not points:
                    break

                for point in points:
                    payload = point.payload or {}

                    point_id = str(point.id)

                    # Prefer chunk_hash because the same logical chunk
                    # should not appear multiple times in the BM25 index.
                    chunk_hash = _as_string(
                        payload.get("chunk_hash")
                    ).strip()

                    identity = (
                        f"chunk:{chunk_hash}"
                        if chunk_hash
                        else f"point:{point_id}"
                    )

                    if identity not in points_by_identity:
                        points_by_identity[identity] = (
                            point_id,
                            payload,
                        )

                pages_fetched += 1

                if next_offset is None:
                    break

                offset = next_offset

            unique_points = list(points_by_identity.values())

            print(
                f"SPARSE SEARCH: Fetched {sum(1 for _ in points_by_identity.values())} "
                f"unique points in {pages_fetched} page(s) "
                f"from '{collection_name}'"
            )

            if not unique_points:
                logger.info(
                    "sparse_search_empty_collection",
                    collection=collection_name,
                    repo_name=context.repo_name,
                )
                print("SPARSE SEARCH: Collection appears empty")
                return []

            # ---------------------------------------------------------------
            # Step 2: Build one BM25 document per unique chunk.
            # ---------------------------------------------------------------

            indexed_chunks: list[_IndexedChunk] = []

            for point_id, payload in unique_points:
                function_name = _as_string(
                    payload.get("function_name")
                )

                class_name = _as_string(
                    payload.get("class_name")
                )

                code = _as_string(
                    payload.get("code")
                    or payload.get("content")
                    or ""
                )

                code = code[:_MAX_CODE_CHARS]

                function_tokens = _tokenize(function_name)
                class_tokens = _tokenize(class_name)
                code_tokens = _tokenize(code)

                metadata = dict(payload)
                metadata["_qdrant_collection"] = collection_name

                chunk = RetrievedChunk(
                    chunk_hash=_as_string(
                        payload.get("chunk_hash") or point_id
                    ),
                    file_path=_as_string(
                        payload.get("file_path")
                        or payload.get("source")
                        or ""
                    ),
                    content=code,
                    score=0.0,
                    metadata=metadata,
                )

                indexed_chunks.append(
                    _IndexedChunk(
                        point_id=point_id,
                        payload=payload,
                        function_tokens=function_tokens,
                        class_tokens=class_tokens,
                        code_tokens=code_tokens,
                        chunk=chunk,
                    )
                )

            print(
                f"SPARSE SEARCH: Built BM25 index with "
                f"{len(indexed_chunks)} unique documents"
            )

            # ---------------------------------------------------------------
            # Step 3: Calculate corpus document frequencies.
            #
            # This makes the IDF a real corpus-based BM25 value instead of
            # assuming that a term occurs in 5% or 15% of documents.
            # ---------------------------------------------------------------

            fn_df: Counter[str] = Counter()
            class_df: Counter[str] = Counter()
            code_df: Counter[str] = Counter()

            for item in indexed_chunks:
                fn_df.update(set(item.function_tokens))
                class_df.update(set(item.class_tokens))
                code_df.update(set(item.code_tokens))

            n_docs = len(indexed_chunks)

            # Average field lengths are calculated from the actual corpus.
            avg_fn_len = (
                sum(len(item.function_tokens) for item in indexed_chunks)
                / n_docs
                if n_docs
                else 1.0
            )

            avg_class_len = (
                sum(len(item.class_tokens) for item in indexed_chunks)
                / n_docs
                if n_docs
                else 1.0
            )

            avg_code_len = (
                sum(len(item.code_tokens) for item in indexed_chunks)
                / n_docs
                if n_docs
                else 1.0
            )

            avg_fn_len = max(avg_fn_len, 1.0)
            avg_class_len = max(avg_class_len, 1.0)
            avg_code_len = max(avg_code_len, 1.0)

            # ---------------------------------------------------------------
            # Step 4: Score every unique document.
            # ---------------------------------------------------------------

            scored: list[tuple[float, int]] = []

            for index, item in enumerate(indexed_chunks):
                score = _bm25_score(
                    item=item,
                    query_terms=query_terms,
                    n_docs=n_docs,
                    fn_df=fn_df,
                    class_df=class_df,
                    code_df=code_df,
                    avg_fn_len=avg_fn_len,
                    avg_class_len=avg_class_len,
                    avg_code_len=avg_code_len,
                )

                if score > 0.0:
                    scored.append((score, index))

            # Highest score first.
            scored.sort(
                key=lambda value: value[0],
                reverse=True,
            )

            # ---------------------------------------------------------------
            # Step 5: Convert BM25 results to RetrievedChunk.
            # ---------------------------------------------------------------

            chunks: list[RetrievedChunk] = []

            seen_chunk_hashes: set[str] = set()

            for score, index in scored:
                if len(chunks) >= limit:
                    break

                original_chunk = indexed_chunks[index].chunk

                chunk_hash = original_chunk.chunk_hash

                # Final safety guard against duplicate logical chunks.
                if chunk_hash in seen_chunk_hashes:
                    continue

                seen_chunk_hashes.add(chunk_hash)

                metadata = dict(original_chunk.metadata)
                metadata["_sparse_score"] = float(score)
                metadata["_lexical_score"] = float(score)

                chunks.append(
                    RetrievedChunk(
                        chunk_hash=original_chunk.chunk_hash,
                        file_path=original_chunk.file_path,
                        content=original_chunk.content,
                        score=float(score),
                        metadata=metadata,
                    )
                )

            print(
                f"SPARSE SEARCH: {len(scored)} unique points "
                f"scored > 0; returning {len(chunks)} unique chunks"
            )

            # ---------------------------------------------------------------
            # Debug output
            # ---------------------------------------------------------------

            print(
                f"\nSPARSE SEARCH: Retrieved "
                f"{len(chunks)} lexical chunks"
            )

            for idx, chunk in enumerate(chunks[:10], start=1):
                print(f"\n--- Sparse Result {idx} ---")

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

                print("File:", chunk.file_path)
                print("BM25 Score:", round(chunk.score, 4))
                print("Chunk Hash:", chunk.chunk_hash)

                print(
                    "Code (first 200 chars):",
                    chunk.content[:200],
                )

            logger.info(
                "sparse_search_complete",
                hits=len(chunks),
                terms=len(query_terms),
                collection=collection_name,
                repo_name=context.repo_name,
                total_scrolled=len(unique_points),
                pages_fetched=pages_fetched,
            )

            return chunks

        except Exception as exc:
            logger.warning(
                "sparse_search_failed_continuing_with_dense",
                error=str(exc),
                collection=collection_name,
                repo_name=context.repo_name,
            )

            print(
                "SPARSE SEARCH FAILED — "
                "CONTINUING WITH DENSE RESULTS"
            )
            print("ERROR:", exc)

            return []


# ---------------------------------------------------------------------------
# Query term construction
# ---------------------------------------------------------------------------


def _build_terms(context: SearchContext) -> list[str]:
    """
    Build code-aware query terms.

    Priority:
        1. Explicit identifiers
        2. Extracted keywords
        3. Raw query words

    Both phrases and code identifiers are split into searchable tokens.

    Example:

        "Add functionality to reset the file status tracking."

    becomes approximately:

        ["add", "functionality", "reset", "file", "status", "tracking"]

    An identifier such as:

        "getFileProcessStatus"

    becomes:

        ["getfileprocessstatus", "get", "file", "process", "status"]
    """

    raw_terms: list[str] = []

    raw_terms.extend(
        term
        for term in (context.identifiers or [])
        if isinstance(term, str)
    )

    raw_terms.extend(
        term
        for term in (context.keywords or [])
        if isinstance(term, str)
    )

    # Always include the raw query as a fallback/additional lexical signal.
    if context.query:
        raw_terms.append(context.query)

    terms: list[str] = []
    seen: set[str] = set()

    for raw_term in raw_terms:
        if not isinstance(raw_term, str):
            continue

        for token in _tokenize(raw_term):
            if len(token) <= 1:
                continue

            if token in seen:
                continue

            seen.add(token)
            terms.append(token)

            if len(terms) >= _MAX_TERMS:
                return terms

    return terms


# ---------------------------------------------------------------------------
# Code-aware tokenizer
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    """
    Convert natural language and source-code identifiers into tokens.

    Examples:

        getFileProcessStatus
        ->
        getfileprocessstatus
        get
        file
        process
        status

        fileStatusMap
        ->
        filestatusmap
        file
        status
        map
    """

    if not text:
        return []

    text = str(text)

    # Handle acronyms before camelCase splitting.
    # HTTPServer -> HTTP Server
    text = re.sub(
        r"([A-Z]+)([A-Z][a-z])",
        r"\1 \2",
        text,
    )

    # camelCase / PascalCase:
    # getFile -> get File
    text = re.sub(
        r"([a-z0-9])([A-Z])",
        r"\1 \2",
        text,
    )

    # Replace separators with spaces.
    text = re.sub(
        r"[^a-zA-Z0-9]+",
        " ",
        text,
    )

    raw_tokens = [
        token.lower()
        for token in text.split()
        if len(token) > 1
    ]

    tokens: list[str] = []

    for token in raw_tokens:
        # Preserve the complete identifier token.
        tokens.append(token)

        # Add useful subparts from long code identifiers.
        if len(token) > 3:
            parts = _split_identifier_token(token)

            for part in parts:
                if len(part) > 1 and part not in tokens:
                    tokens.append(part)

    return tokens


def _split_identifier_token(token: str) -> list[str]:
    """
    Split common concatenated identifier words.

    This is intentionally conservative. The complete identifier remains
    in the token list, while common code words are extracted where possible.
    """

    common_parts = (
        "process",
        "status",
        "file",
        "user",
        "record",
        "service",
        "controller",
        "repository",
        "repo",
        "create",
        "update",
        "delete",
        "remove",
        "reset",
        "clear",
        "get",
        "set",
        "find",
        "save",
        "upload",
        "download",
        "validate",
        "check",
        "handle",
        "create",
        "add",
    )

    parts: list[str] = []
    remaining = token

    # Longest terms first prevents smaller terms from consuming the
    # identifier prematurely.
    for part in sorted(
        set(common_parts),
        key=len,
        reverse=True,
    ):
        if part in remaining:
            parts.append(part)

    return parts


# ---------------------------------------------------------------------------
# BM25 scoring
# ---------------------------------------------------------------------------


def _bm25_score(
    item: _IndexedChunk,
    query_terms: list[str],
    n_docs: int,
    fn_df: Counter[str],
    class_df: Counter[str],
    code_df: Counter[str],
    avg_fn_len: float,
    avg_class_len: float,
    avg_code_len: float,
) -> float:
    """
    Calculate weighted BM25 for one indexed chunk.

    Each field is scored independently:

        function_name -> weight 4.0
        class_name    -> weight 3.0
        code          -> weight 1.0

    The field scores are then combined.
    """

    if not query_terms or n_docs <= 0:
        return 0.0

    total = 0.0

    for term in query_terms:
        term = term.lower()

        # ---------------------------------------------------------------
        # Function name
        # ---------------------------------------------------------------

        total += _field_bm25(
            tokens=item.function_tokens,
            term=term,
            document_frequency=fn_df.get(term, 0),
            n_docs=n_docs,
            average_length=avg_fn_len,
            weight=_WEIGHT_FUNCTION_NAME,
        )

        # ---------------------------------------------------------------
        # Class name
        # ---------------------------------------------------------------

        total += _field_bm25(
            tokens=item.class_tokens,
            term=term,
            document_frequency=class_df.get(term, 0),
            n_docs=n_docs,
            average_length=avg_class_len,
            weight=_WEIGHT_CLASS_NAME,
        )

        # ---------------------------------------------------------------
        # Code
        # ---------------------------------------------------------------

        total += _field_bm25(
            tokens=item.code_tokens,
            term=term,
            document_frequency=code_df.get(term, 0),
            n_docs=n_docs,
            average_length=avg_code_len,
            weight=_WEIGHT_CODE,
        )

    return total


def _field_bm25(
    tokens: list[str],
    term: str,
    document_frequency: int,
    n_docs: int,
    average_length: float,
    weight: float,
) -> float:
    """Calculate one weighted BM25 field contribution."""

    if not tokens:
        return 0.0

    tf = tokens.count(term)

    if tf <= 0:
        return 0.0

    if document_frequency <= 0:
        return 0.0

    # Standard BM25 IDF.
    idf = math.log(
        1.0
        + (
            (n_docs - document_frequency + 0.5)
            / (document_frequency + 0.5)
        )
    )

    document_length = len(tokens)

    length_ratio = (
        document_length / average_length
        if average_length > 0
        else 1.0
    )

    denominator = (
        tf
        + _BM25_K1
        * (
            (1.0 - _BM25_B)
            + (_BM25_B * length_ratio)
        )
    )

    if denominator <= 0:
        return 0.0

    tf_component = (
        tf * (_BM25_K1 + 1.0)
    ) / denominator

    return weight * idf * tf_component


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _as_string(value: Any) -> str:
    """Safely convert payload values to strings."""

    if value is None:
        return ""

    if isinstance(value, str):
        return value

    return str(value)

