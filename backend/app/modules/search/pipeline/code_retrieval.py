"""
app/modules/search/pipeline/code_retrieval.py

Pipeline stage: Code Retrieval.

Generates the query embedding and performs hybrid retrieval
against Qdrant.
"""

from __future__ import annotations

import re

from app.core.enums import IntentType
from app.core.logging import get_logger
from app.modules.embedding.service.embedding_service import (
    generate_embeddings,
)
from app.modules.search.domain.search_domain import RetrievedChunk, SearchContext
from app.modules.search.retrieval.hybrid_search import HybridSearch

logger = get_logger(__name__)


class CodeRetrievalStage:
    """Retrieve relevant code using hybrid search."""

    def __init__(self, hybrid_search: HybridSearch) -> None:
        self.hybrid_search = hybrid_search

    async def execute(
        self,
        context: SearchContext,
        limit: int = 20,
    ) -> None:

        if context.early_exit:
            logger.info(
                "code_retrieval_skipped",
                repo_name=context.repo_name,
                reason=context.early_exit,
            )
            return

        if not context.repo_name:
            context.early_exit = "EARLY_EXIT_A"
            context.early_exit_message = (
                "Repository name is required for code retrieval."
            )
            return

        if not context.qdrant_collection:
            context.early_exit = "EARLY_EXIT_A"
            context.early_exit_message = (
                f"No Qdrant collection resolved for repository '{context.repo_name}'."
            )
            logger.warning(
                "code_retrieval_skipped_no_collection",
                repo_name=context.repo_name,
            )
            return

        if limit <= 0:
            raise ValueError(
                "Code retrieval limit must be greater than zero."
            )

        logger.info(
            "code_retrieval_started",
            repo_name=context.repo_name,
            query=context.query,
            collection=context.qdrant_collection,
            limit=limit,
        )

        # ---------------------------------------------------------
        # Generate query embedding
        # ---------------------------------------------------------

        if context.query_vector is None:

            try:
                vectors = await generate_embeddings(
                    [context.query],
                    input_type="query",
                )

                if not vectors or not vectors[0]:
                    raise ValueError(
                        "Embedding provider returned no query vector."
                    )

                context.query_vector = vectors[0]

                logger.info(
                    "query_embedding_generated",
                    repo_name=context.repo_name,
                    dimension=len(context.query_vector),
                )

            except Exception as exc:

                logger.exception(
                    "query_embedding_failed",
                    repo_name=context.repo_name,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )

                # Keep query_vector as None so HybridSearch can
                # still perform sparse retrieval if supported.
                context.query_vector = None

        # ---------------------------------------------------------
        # Hybrid retrieval
        # ---------------------------------------------------------

        try:
            chunks = await self.hybrid_search.search(
                context,
                limit=limit,
            )

            context.retrieved_chunks = chunks or []

        except Exception as exc:

            logger.exception(
                "hybrid_code_retrieval_failed",
                repo_name=context.repo_name,
                collection=context.qdrant_collection,
                error_type=type(exc).__name__,
                error=str(exc),
            )

            context.retrieved_chunks = []

            context.early_exit = "EARLY_EXIT_B"
            context.early_exit_message = (
                f"Code retrieval failed: "
                f"{type(exc).__name__}: {str(exc)}"
            )

            return

        logger.info(
            "retrieval_results_stored",
            repo_name=context.repo_name,
            collection=context.qdrant_collection,
            result_count=len(context.retrieved_chunks),
        )

        if context.intent == IntentType.FIX_BUG:
            context.retrieved_chunks = await self._expand_bug_candidates(
                context,
                context.retrieved_chunks,
                limit,
            )

        # ---------------------------------------------------------
        # Special handling for package vulnerability:
        # If intent is FIX_VULNERABILITY or query mentions package
        # vulnerability, ONLY package.json and package-lock.json
        # are targeted! All other files are filtered out.
        # ---------------------------------------------------------
        if context.intent == IntentType.FIX_VULNERABILITY or _is_package_vuln_query(context.query):
            await self._target_only_package_dependency_chunks(context)

        # ---------------------------------------------------------
        # No results
        # ---------------------------------------------------------

        if not context.retrieved_chunks:

            context.early_exit = "EARLY_EXIT_B"
            context.early_exit_message = (
                "No relevant code was found for this query in "
                f"repository '{context.repo_name}'. "
                "Try rephrasing or broadening your search."
            )

            logger.warning(
                "no_chunks_retrieved",
                repo_name=context.repo_name,
                query=context.query,
                collection=context.qdrant_collection,
                limit=limit,
                query_vector_available=(
                    context.query_vector is not None
                ),
            )

            return

        logger.info(
            "code_retrieval_completed",
            repo_name=context.repo_name,
            collection=context.qdrant_collection,
            result_count=len(context.retrieved_chunks),
        )

    async def _expand_bug_candidates(
        self,
        context: SearchContext,
        initial_chunks: list[RetrievedChunk],
        limit: int,
    ) -> list[RetrievedChunk]:
        """Run one bounded related-symbol search and rerank the merged chunks."""
        signals = _extract_bug_signals(context.query)
        signal_terms = _unique_terms(
            [
                *signals["entities"],
                *signals["fields"],
                *signals["actions"],
                *signals["errors"],
                *context.keywords,
                *context.identifiers,
            ]
        )

        context.keywords = _unique_terms([*context.keywords, *signal_terms])
        context.identifiers = _unique_terms(
            [*context.identifiers, *signals["entities"], *signals["fields"]]
        )

        original_query = context.query
        initial_related_terms = _extract_related_terms(
            initial_chunks,
            signal_terms,
        )
        first_terms = _unique_terms([*signal_terms, *initial_related_terms])[:16]
        result_sets = [initial_chunks]
        related_chunks: list[RetrievedChunk] = []

        if first_terms:
            related_chunks = await self._search_bug_expansion(
                context,
                f"{original_query} {' '.join(first_terms)}".strip(),
                limit,
            )
            result_sets.append(related_chunks)

        # Follow references found in the related chunks once; this is a
        # bounded second-degree search, not a retry on failed requests.
        used_terms = {term.lower() for term in first_terms}
        second_related_terms = [
            term
            for term in _extract_related_terms(related_chunks, signal_terms)
            if term.lower() not in used_terms
        ]
        second_terms = _unique_terms(
            [*signal_terms, *second_related_terms]
        )[:16]
        if second_related_terms:
            second_chunks = await self._search_bug_expansion(
                context,
                f"{original_query} {' '.join(second_terms)}".strip(),
                limit,
            )
            result_sets.append(second_chunks)

        related_terms = _unique_terms(
            [*initial_related_terms, *second_related_terms]
        )

        merged = _rerank_bug_chunks(result_sets, signal_terms)
        related_count = sum(len(result_set) for result_set in result_sets[1:])
        logger.info(
            "fix_bug_candidates_expanded",
            initial_count=len(initial_chunks),
            related_count=related_count,
            merged_count=len(merged),
            signal_count=len(signal_terms),
            related_term_count=len(related_terms),
        )
        return merged[:max(limit, 32)]

    async def _search_bug_expansion(
        self,
        context: SearchContext,
        expanded_query: str,
        limit: int,
    ) -> list[RetrievedChunk]:
        """Search an expanded FIX_BUG query and restore the original context."""
        original_query = context.query
        original_vector = context.query_vector
        expanded_vector = None
        try:
            vectors = await generate_embeddings(
                [expanded_query],
                input_type="query",
            )
            expanded_vector = vectors[0] if vectors and vectors[0] else None
        except Exception as exc:
            logger.warning(
                "fix_bug_expanded_embedding_failed_using_sparse_retrieval",
                repo_name=context.repo_name,
                error_type=type(exc).__name__,
            )

        try:
            context.query = expanded_query
            context.query_vector = expanded_vector
            return await self.hybrid_search.search(
                context,
                limit=max(limit, 24),
            ) or []
        except Exception as exc:
            logger.warning(
                "fix_bug_related_retrieval_failed",
                repo_name=context.repo_name,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return []
        finally:
            context.query = original_query
            context.query_vector = original_vector

    async def _target_only_package_dependency_chunks(
        self,
        context: SearchContext,
    ) -> None:
        """
        Ensure that for package vulnerability tasks, ONLY package.json
        and package-lock.json are targeted and retained in retrieved_chunks.
        All unrelated files (e.g. backend source code) are excluded.
        """
        def _is_package_file(file_path: str) -> bool:
            clean = (file_path or "").replace("\\", "/").lower()
            return clean.endswith("package.json") or clean.endswith("package-lock.json")

        # 1. Filter existing retrieved chunks to keep only package.json and package-lock.json
        filtered_chunks: list[RetrievedChunk] = [
            c for c in context.retrieved_chunks
            if _is_package_file(getattr(c, "file_path", ""))
        ]

        # 2. If package.json or package-lock.json was missed by vector search,
        # actively scroll Qdrant to find all package.json and package-lock.json points
        has_pkg_json = any(
            (getattr(c, "file_path", "") or "").replace("\\", "/").lower().endswith("package.json")
            for c in filtered_chunks
        )
        has_lock = any(
            (getattr(c, "file_path", "") or "").replace("\\", "/").lower().endswith("package-lock.json")
            for c in filtered_chunks
        )

        if (not has_pkg_json or not has_lock) and context.qdrant_collection:
            try:
                from app.infrastructure.qdrant.client import get_qdrant_client
                client = get_qdrant_client()
                records, _ = await client.scroll(
                    collection_name=context.qdrant_collection,
                    limit=500,
                    with_payload=True,
                    with_vectors=False,
                )
                existing_hashes = {getattr(c, "chunk_hash", "") for c in filtered_chunks}
                for rec in records:
                    payload = rec.payload or {}
                    fp = payload.get("file_path", "")
                    if _is_package_file(fp):
                        h = payload.get("chunk_hash") or str(rec.id)
                        if h not in existing_hashes:
                            existing_hashes.add(h)
                            code = payload.get("code") or payload.get("content") or ""
                            chunk = RetrievedChunk(
                                chunk_hash=h,
                                file_path=fp,
                                content=code,
                                score=1.0 if fp.lower().endswith("package.json") else 0.95,
                                metadata=payload,
                            )
                            filtered_chunks.append(chunk)
            except Exception as exc:
                logger.warning("package_chunk_qdrant_scroll_failed", error=str(exc))

        # 3. Sort: package.json chunks first, then package-lock.json chunks
        def _sort_key(c: RetrievedChunk) -> tuple[int, int]:
            fp = (getattr(c, "file_path", "") or "").replace("\\", "/").lower()
            priority = 0 if fp.endswith("package.json") else 1
            meta = c.metadata or {}
            start_line = meta.get("start_line") or getattr(c, "start_line", 0) or 0
            return (priority, start_line)

        filtered_chunks.sort(key=_sort_key)

        if filtered_chunks:
            context.retrieved_chunks = filtered_chunks
            # Clear early exit if any was set earlier due to missing chunks
            context.early_exit = None
            context.early_exit_message = None


def _is_package_vuln_query(query: str | None) -> bool:
    if not query:
        return False
    q = query.lower()
    return (
        "package.json" in q
        or "vulnerab" in q
        or "audit" in q
        or ("package" in q and ("fix" in q or "update" in q or "patch" in q))
    )


_BUG_STOP_WORDS = {
    "a", "an", "and", "are", "at", "be", "bug", "by", "for", "from",
    "fix", "in", "is", "it", "of", "on", "or", "please", "the", "to",
    "with", "when", "where", "which", "why", "how", "issue", "problem",
}
_BUG_ACTIONS = {
    "add", "calculate", "change", "choose", "create", "delete", "fetch",
    "get", "load", "parse", "remove", "save", "select", "selection", "set",
    "submit", "update", "validate", "render", "show", "hide", "open", "close",
}
_BUG_ERRORS = {
    "broken", "cannot", "crash", "doesnt", "empty", "error", "fail", "fails",
    "failed", "failure", "incorrect", "invalid", "missing", "never", "not",
    "rejected", "wrong", "unexpected", "unavailable",
}


def _extract_bug_signals(query: str) -> dict[str, list[str]]:
    """Extract deterministic entities, fields, actions, and error terms."""
    terms = _tokenize(query)
    actions = [term for term in terms if term in _BUG_ACTIONS]
    errors = [term for term in terms if term in _BUG_ERRORS]
    fields = [
        term for term in terms
        if term in {
            "date", "time", "status", "id", "name", "email", "address",
            "value", "type", "state", "count", "amount", "price", "password",
            "token", "path", "url", "selection", "selected",
        }
    ]
    excluded = _BUG_STOP_WORDS | set(actions) | set(errors) | set(fields)
    entities = [term for term in terms if term not in excluded and len(term) > 2]
    return {
        "entities": _unique_terms(entities),
        "fields": _unique_terms(fields),
        "actions": _unique_terms(actions),
        "errors": _unique_terms(errors),
    }


def _extract_related_terms(
    chunks: list[RetrievedChunk],
    signal_terms: list[str],
) -> list[str]:
    """Collect nearby symbols, imports, route paths, and declarations for expansion."""
    terms: list[str] = []
    signal_set = {term.lower() for term in signal_terms}
    for chunk in chunks[:12]:
        metadata = chunk.metadata or {}
        for key in ("function_name", "class_name", "symbol"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                terms.append(value.strip())

        path_stem = chunk.file_path.replace("\\", "/").rsplit("/", 1)[-1]
        path_stem = re.sub(r"\.[^.]+$", "", path_stem)
        if len(path_stem) > 3:
            terms.append(path_stem)

        source = chunk.content or ""
        terms.extend(re.findall(
            r"(?m)^\s*(?:async\s+)?(?:def|class|function|const|let|var)\s+([A-Za-z_$][\w$]*)",
            source,
        ))
        terms.extend(re.findall(
            r"(?:from\s+|require\s*\(|import\s*\(?\s*)[\"']?([.\w/-]+)",
            source,
        ))
        terms.extend(re.findall(
            r"\bfrom\s+[\w.]+\s+import\s+([A-Za-z_]\w*)",
            source,
        ))
        for import_list in re.findall(
            r"\bimport\s*\{([^}]+)\}\s*from",
            source,
        ):
            terms.extend(
                item.split(" as ", 1)[0].strip()
                for item in import_list.split(",")
            )
        terms.extend(re.findall(
            r"(?:\.get|\.post|\.put|\.patch|\.delete|route)\s*\(\s*[\"'](/[^\"']+)",
            source,
            flags=re.IGNORECASE,
        ))

    filtered = []
    for term in terms:
        term = term.strip(" ./\\'\"`()")
        if len(term) < 4:
            continue
        normalized = set(_tokenize(term))
        if normalized and normalized.issubset(signal_set):
            continue
        filtered.append(term)
    return _unique_terms(filtered)[:10]


def _rerank_bug_chunks(
    result_sets: list[list[RetrievedChunk]],
    signal_terms: list[str],
) -> list[RetrievedChunk]:
    """Combine hybrid rank, exact report-term hits, and cross-file references."""
    chunks_by_key: dict[str, RetrievedChunk] = {}
    semantic_scores: dict[str, float] = {}

    for results in result_sets:
        denominator = max(len(results), 1)
        for rank, chunk in enumerate(results):
            key = _chunk_key(chunk)
            semantic_scores[key] = max(
                semantic_scores.get(key, 0.0),
                1.0 - (rank / denominator),
            )
            if key not in chunks_by_key or chunk.score > chunks_by_key[key].score:
                chunks_by_key[key] = chunk

    chunks = list(chunks_by_key.values())
    aliases_by_key = { _chunk_key(chunk): _chunk_aliases(chunk) for chunk in chunks }
    related_by_key: dict[str, set[str]] = { _chunk_key(chunk): set() for chunk in chunks }

    for source in chunks:
        source_key = _chunk_key(source)
        source_text = (source.content or "").lower()
        for target in chunks:
            target_key = _chunk_key(target)
            if target_key == source_key or target.file_path == source.file_path:
                continue
            if any(_contains_term(source_text, alias) for alias in aliases_by_key[target_key]):
                related_by_key[source_key].add(target_key)
                related_by_key[target_key].add(source_key)

    signal_set = set(signal_terms)
    for chunk in chunks:
        key = _chunk_key(chunk)
        searchable = set(_tokenize(
            " ".join([
                chunk.file_path,
                str(chunk.metadata.get("function_name") or ""),
                str(chunk.metadata.get("class_name") or ""),
                str(chunk.metadata.get("symbol") or ""),
                chunk.content or "",
            ])
        ))
        exact_ratio = (
            len(signal_set & searchable) / len(signal_set)
            if signal_set
            else 0.0
        )
        relationship = min(len(related_by_key[key]) / 2.0, 1.0)
        semantic = semantic_scores[key]
        chunk.metadata["_fix_bug_related_hashes"] = sorted(related_by_key[key])
        chunk.score = 0.65 * semantic + 0.25 * exact_ratio + 0.10 * relationship

    return sorted(
        chunks,
        key=lambda chunk: (chunk.score, chunk.file_path.lower()),
        reverse=True,
    )


def _chunk_aliases(chunk: RetrievedChunk) -> set[str]:
    metadata = chunk.metadata or {}
    aliases = {
        str(metadata.get(key) or "").strip().lower()
        for key in ("function_name", "class_name", "symbol")
    }
    basename = chunk.file_path.replace("\\", "/").rsplit("/", 1)[-1]
    stem = re.sub(r"\.[^.]+$", "", basename).lower()
    if len(stem) > 4:
        aliases.add(stem)
    return {alias for alias in aliases if len(alias) > 3}


def _chunk_key(chunk: RetrievedChunk) -> str:
    if chunk.chunk_hash:
        return f"hash:{chunk.chunk_hash}"
    return f"{chunk.file_path}:{chunk.content}"


def _contains_term(source: str, term: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", source, re.IGNORECASE) is not None


def _tokenize(value: str) -> list[str]:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    return [term.lower() for term in re.findall(r"[A-Za-z][A-Za-z0-9]*", value)]


def _unique_terms(terms: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for term in terms:
        if not isinstance(term, str):
            continue
        value = term.strip()
        key = value.lower()
        if value and key not in seen:
            unique.append(value)
            seen.add(key)
    return unique