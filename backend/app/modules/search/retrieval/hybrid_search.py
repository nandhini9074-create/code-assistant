"""
app/modules/search/retrieval/hybrid_search.py

Orchestrates dense retrieval, sparse lexical retrieval, result merging,
deduplication, and final reranking.

Flow:
    Dense Search + Sparse Search
    ↓
    Merge ALL results
    ↓
    Deduplicate
    ↓
    Cross-Encoder Rerank
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.modules.search.domain.search_domain import (
    RetrievedChunk,
    SearchContext,
)
from app.modules.search.retrieval.dense_search import DenseSearch
from app.modules.search.retrieval.reranker import Reranker
from app.modules.search.retrieval.result_merger import ResultMerger
from app.modules.search.retrieval.sparse_search import SparseSearch

logger = get_logger(__name__)

PRESERVE_FIELDS = [
    "repo_name",
    "repo_id",
    "_qdrant_collection",
    "file_path",
    "function_name",
    "class_name",
    "chunk_type",
    "chunk_hash",
    "code",
    "start_line",
    "end_line",
]


def _enrich_chunk_metadata(chunk: RetrievedChunk) -> None:
    """Ensure chunk attributes and metadata dictionary contain all key fields."""
    if chunk.metadata is None:
        chunk.metadata = {}
    meta = chunk.metadata

    if not chunk.chunk_hash and meta.get("chunk_hash"):
        chunk.chunk_hash = str(meta["chunk_hash"])
    if not chunk.file_path and (meta.get("file_path") or meta.get("source")):
        chunk.file_path = str(meta.get("file_path") or meta.get("source"))
    if not chunk.content and (meta.get("code") or meta.get("content")):
        chunk.content = str(meta.get("code") or meta.get("content"))

    for field_name in PRESERVE_FIELDS:
        if field_name not in meta or meta[field_name] is None:
            if field_name == "file_path":
                meta[field_name] = chunk.file_path
            elif field_name == "code":
                meta[field_name] = chunk.content
            elif field_name == "chunk_hash":
                meta[field_name] = chunk.chunk_hash


def _merge_chunk_metadata(target: RetrievedChunk, source: RetrievedChunk) -> None:
    """Preserve the best information/metadata across duplicated chunks."""
    _enrich_chunk_metadata(target)
    _enrich_chunk_metadata(source)

    for field_name in PRESERVE_FIELDS:
        src_val = source.metadata.get(field_name)
        target_val = target.metadata.get(field_name)

        is_target_empty = (
            target_val is None
            or str(target_val).strip() == ""
            or str(target_val).lower() == "none"
        )
        is_src_non_empty = (
            src_val is not None
            and str(src_val).strip() != ""
            and str(src_val).lower() != "none"
        )

        if is_target_empty and is_src_non_empty:
            target.metadata[field_name] = src_val
            if field_name == "file_path" and not target.file_path:
                target.file_path = str(src_val)
            elif field_name == "code" and not target.content:
                target.content = str(src_val)
            elif field_name == "chunk_hash" and not target.chunk_hash:
                target.chunk_hash = str(src_val)


class HybridSearch:
    """Combine dense and sparse retrieval strategies."""

    def __init__(
        self,
        dense: DenseSearch,
        sparse: SparseSearch,
        merger: ResultMerger | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        self.dense = dense
        self.sparse = sparse
        self.merger = merger or ResultMerger()
        self.reranker = reranker or Reranker()

    async def search(
        self,
        context: SearchContext,
        limit: int = 20,
    ) -> list[RetrievedChunk]:

        print("\n========== HYBRID SEARCH START ==========")
        print("REPO NAME:", context.repo_name)
        print("COLLECTION:", context.qdrant_collection)
        print("QUERY VECTOR EXISTS:", bool(context.query_vector))
        print(
            "QUERY VECTOR DIMENSION:",
            len(context.query_vector) if context.query_vector else 0,
        )

        # ---------------------------------------------------------
        # 1. Early exit
        # ---------------------------------------------------------
        if context.early_exit:
            print("HYBRID SEARCH: EARLY EXIT ALREADY SET:", context.early_exit)
            return []

        # ---------------------------------------------------------
        # 2. Validate repository
        # ---------------------------------------------------------
        if not context.repo_name:
            print("HYBRID SEARCH: Missing repository name")
            return []

        # ---------------------------------------------------------
        # 3. Validate limit
        # ---------------------------------------------------------
        if limit <= 0:
            print("HYBRID SEARCH: INVALID LIMIT")
            return []

        # ---------------------------------------------------------
        # 4. Dense retrieval
        # Keep existing Qdrant dense search. Return candidates up to limit.
        # Never discard dense results because sparse search fails.
        # ---------------------------------------------------------
        print("HYBRID SEARCH: CALLING DENSE SEARCH")
        dense_results = await self.dense.search(context, limit=limit) or []
        print(f"DENSE RESULTS: {len(dense_results)}")

        # ---------------------------------------------------------
        # 5. Sparse retrieval
        # Sparse is optional. If it succeeds, use its results.
        # If it fails for any reason, log:
        # SPARSE SEARCH FAILED — CONTINUING WITH DENSE RESULTS
        # Return [] and continue. Never set early_exit because sparse failed.
        # ---------------------------------------------------------
        print("HYBRID SEARCH: CALLING SPARSE SEARCH")
        try:
            sparse_results = await self.sparse.search(context, limit=limit) or []
        except Exception as exc:
            logger.warning(
                "SPARSE SEARCH FAILED — CONTINUING WITH DENSE RESULTS",
                error=str(exc),
            )
            print("SPARSE SEARCH FAILED — CONTINUING WITH DENSE RESULTS")
            sparse_results = []

        print(f"SPARSE RESULTS: {len(sparse_results)}")

        # ---------------------------------------------------------
        # 6. Hybrid Merge: merged_results = dense_results + sparse_results
        # Both sources participate. If either unavailable, continue with other.
        # Ensure results are only from the selected collection.
        # ---------------------------------------------------------
        merged_results = dense_results + sparse_results
        if context.qdrant_collection:
            merged_results = [
                chunk for chunk in merged_results
                if chunk.metadata.get("_qdrant_collection") == context.qdrant_collection
                or not chunk.metadata.get("_qdrant_collection")
            ]
            for chunk in merged_results:
                chunk.metadata["_qdrant_collection"] = context.qdrant_collection
        print(f"MERGED RESULTS: {len(merged_results)}")

        # ---------------------------------------------------------
        # 7. Deduplicate before reranking
        # Prefer chunk_hash. Fallback: _qdrant_collection + file_path + content/code
        # Preserve the best information/metadata.
        # ---------------------------------------------------------
        deduplicated_results = self.deduplicate_chunks(merged_results)
        print(f"DEDUPLICATED RESULTS: {len(deduplicated_results)}")

        if not deduplicated_results:
            print("RERANKED RESULTS: 0")
            print("========== HYBRID SEARCH END ==========\n")
            return []

        # ---------------------------------------------------------
        # 8. Cross-Encoder Rerank
        # Use existing Cross-Encoder reranker on complete deduplicated merged set.
        # ---------------------------------------------------------
        print("HYBRID SEARCH: CALLING RERANKER")
        reranked_results = self.reranker.rerank(
            context,
            deduplicated_results,
            top_k=limit,
        )
        print(f"RERANKED RESULTS: {len(reranked_results)}")

        print("========== HYBRID SEARCH END ==========\n")

        return reranked_results

    @classmethod
    def deduplicate_chunks(
        cls,
        chunks: list[RetrievedChunk],
    ) -> list[RetrievedChunk]:
        """
        Deduplicate chunks before reranking.

        Prefer chunk_hash.
        Fallback: _qdrant_collection + file_path + content/code.

        Preserve the best information/metadata:
        repo_name, repo_id, _qdrant_collection, file_path, function_name,
        class_name, chunk_type, chunk_hash, code, start_line, end_line.
        """
        dedup_map: dict[str, RetrievedChunk] = {}

        for chunk in chunks:
            chunk_hash = getattr(chunk, "chunk_hash", "") or chunk.metadata.get("chunk_hash") or ""
            if chunk_hash:
                key = f"hash:{chunk_hash}"
            else:
                coll = str(chunk.metadata.get("_qdrant_collection", ""))
                fp = str(chunk.file_path or chunk.metadata.get("file_path", ""))
                content = str(chunk.content or chunk.metadata.get("code", ""))
                key = f"fallback:{coll}:{fp}:{content}"

            if key not in dedup_map:
                _enrich_chunk_metadata(chunk)
                dedup_map[key] = chunk
            else:
                existing = dedup_map[key]
                _merge_chunk_metadata(existing, chunk)
                if chunk.score > existing.score:
                    existing.score = chunk.score

        return list(dedup_map.values())