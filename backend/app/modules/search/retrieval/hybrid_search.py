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
from app.modules.search.domain.search_domain import RetrievedChunk, SearchContext
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


class HybridSearch:
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

    @staticmethod
    def _enrich_chunk_metadata(chunk: RetrievedChunk) -> RetrievedChunk:
        """
        Ensure important metadata fields are preserved on the retrieved chunk.
        """

        metadata = getattr(chunk, "metadata", None)

        if metadata is None:
            metadata = {}

        for field in PRESERVE_FIELDS:
            value = getattr(chunk, field, None)

            if value is not None and field not in metadata:
                metadata[field] = value

        if "chunk_hash" not in metadata:
            chunk_hash = getattr(chunk, "chunk_hash", None)

            if chunk_hash:
                metadata["chunk_hash"] = chunk_hash

        if "file_path" not in metadata:
            file_path = getattr(chunk, "file_path", None)

            if file_path:
                metadata["file_path"] = file_path

        if "content" not in metadata:
            code = getattr(chunk, "code", None)

            if code:
                metadata["content"] = code

        chunk.metadata = metadata

        return chunk

    @staticmethod
    def _merge_chunk_metadata(
        target: RetrievedChunk,
        source: RetrievedChunk,
    ) -> RetrievedChunk:
        """
        Merge missing metadata from a duplicate source chunk into the target.
        Keep the higher score.
        """

        target_metadata = getattr(target, "metadata", None) or {}
        source_metadata = getattr(source, "metadata", None) or {}

        for key, value in source_metadata.items():
            if key not in target_metadata or target_metadata[key] in (None, ""):
                target_metadata[key] = value

        target.metadata = target_metadata

        target_score = getattr(target, "score", 0.0) or 0.0
        source_score = getattr(source, "score", 0.0) or 0.0

        if source_score > target_score:
            target.score = source_score

        return target

    def deduplicate_chunks(
        self,
        chunks: list[RetrievedChunk],
    ) -> list[RetrievedChunk]:
        """
        Deduplicate retrieved chunks.

        Primary key:
            chunk_hash

        Fallback key:
            collection + file_path + code/content
        """

        unique_chunks: dict[str, RetrievedChunk] = {}

        for chunk in chunks:
            chunk = self._enrich_chunk_metadata(chunk)

            metadata: dict[str, Any] = getattr(chunk, "metadata", None) or {}

            chunk_hash = (
                getattr(chunk, "chunk_hash", None)
                or metadata.get("chunk_hash")
            )

            if chunk_hash:
                dedupe_key = f"hash:{chunk_hash}"
            else:
                collection = (
                    getattr(chunk, "_qdrant_collection", None)
                    or metadata.get("_qdrant_collection")
                    or ""
                )

                file_path = (
                    getattr(chunk, "file_path", None)
                    or metadata.get("file_path")
                    or ""
                )

                content = (
                    getattr(chunk, "code", None)
                    or metadata.get("content")
                    or metadata.get("code")
                    or ""
                )

                dedupe_key = (
                    f"content:{collection}:{file_path}:{content}"
                )

            if dedupe_key in unique_chunks:
                unique_chunks[dedupe_key] = self._merge_chunk_metadata(
                    unique_chunks[dedupe_key],
                    chunk,
                )
            else:
                unique_chunks[dedupe_key] = chunk

        return list(unique_chunks.values())

    async def search(
        self,
        context: SearchContext,
        limit: int = 10,
    ) -> list[RetrievedChunk]:
        logger.info(
            "hybrid_search_started",
            repo_name=context.repo_name,
            collection=context.qdrant_collection,
            query_vector_exists=bool(context.query_vector),
            query_vector_dimension=(
                len(context.query_vector)
                if context.query_vector
                else 0
            ),
        )

        if context.early_exit:
            logger.info(
                "hybrid_search_early_exit_already_set",
                early_exit=context.early_exit,
            )
            return []

        if not context.repo_name:
            logger.warning(
                "hybrid_search_missing_repository_name",
            )
            return []

        if limit <= 0:
            logger.warning(
                "hybrid_search_invalid_limit",
                limit=limit,
            )
            return []

        logger.info(
            "dense_search_started",
        )

        dense_results = await self.dense.search(
            context,
            limit=limit,
        ) or []

        logger.info(
            "dense_search_completed",
            result_count=len(dense_results),
        )

        logger.info(
            "sparse_search_started",
        )

        try:
            sparse_results = await self.sparse.search(
                context,
                limit=limit,
            ) or []

        except Exception as exc:
            logger.warning(
                "SPARSE SEARCH FAILED — CONTINUING WITH DENSE RESULTS",
                error=str(exc),
            )

            sparse_results = []

        logger.info(
            "sparse_search_completed",
            result_count=len(sparse_results),
        )

        merged_results = self.merger.merge(
              dense_results=dense_results,
               sparse_results=sparse_results,
        )

        logger.info(
            "hybrid_results_merged",
            dense_count=len(dense_results),
            sparse_count=len(sparse_results),
            merged_count=len(merged_results),
        )

        deduplicated_results = self.deduplicate_chunks(
                merged_results
        )

        logger.info(
            "hybrid_results_deduplicated",
            result_count=len(deduplicated_results),
        )

        if not deduplicated_results:
            logger.info(
                "hybrid_reranking_completed",
                result_count=0,
            )
            return []

        logger.info(
            "hybrid_reranking_started",
        )

        reranked_results = self.reranker.rerank(
            context,
            deduplicated_results,
            top_k=limit,
        )

        logger.info(
            "hybrid_reranking_completed",
            result_count=len(reranked_results),
        )

        return reranked_results