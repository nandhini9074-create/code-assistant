"""
app/modules/search/pipeline/code_retrieval.py

Pipeline stage: Code Retrieval.

Generates the query embedding and performs hybrid retrieval
against Qdrant.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.modules.embedding.service.embedding_service import (
    generate_embeddings,
)
from app.modules.search.domain.search_domain import SearchContext
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