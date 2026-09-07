
"""
app/modules/search/pipeline/code_retrieval.py

Pipeline stage: Code Retrieval (Step 6).

Generates a query embedding using the configured embedding provider
and performs hybrid dense + sparse retrieval.

If no usable query embedding can be generated, Early Exit B is set.

If retrieval returns no chunks, Early Exit B is also set.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.modules.embedding.service.embedding_service import generate_embeddings
from app.modules.search.domain.search_domain import SearchContext
from app.modules.search.retrieval.hybrid_search import HybridSearch

logger = get_logger(__name__)


class CodeRetrievalStage:
    """Pipeline stage responsible for retrieving relevant code."""

    def __init__(self, hybrid_search: HybridSearch) -> None:
        self.hybrid_search = hybrid_search

    async def execute(
        self,
        context: SearchContext,
        limit: int = 20,
    ) -> None:
        """
        Execute code retrieval.

        Steps:
        1. Generate a query embedding if one has not already been generated.
        2. Run hybrid dense + sparse retrieval.
        3. Store retrieved chunks in SearchContext.
        4. Trigger Early Exit B when retrieval cannot continue or
           produces no results.
        """

        if context.early_exit:
            logger.info(
                "code_retrieval_skipped",
                reason=context.early_exit,
                repo_id=context.repo_id,
            )
            return

        if limit <= 0:
            raise ValueError("Code retrieval limit must be greater than zero.")

        # ---------------------------------------------------------
        # 1. Generate query embedding
        # ---------------------------------------------------------
        #
        # Reuse an existing query vector when Step 7 broadens
        # retrieval. The query itself has not changed, so there is
        # no reason to call the embedding provider again.
        #
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

            except Exception:
                logger.exception(
                    "query_embedding_failed",
                    repo_id=context.repo_id,
                )

                context.query_vector = None
                context.early_exit = "EARLY_EXIT_B"
                context.early_exit_message = (
                    "Could not generate a query embedding, "
                    "so code retrieval could not be performed."
                )
                return

        logger.info(
            "query_embedding_ready",
            repo_id=context.repo_id,
            dimensions=len(context.query_vector),
        )

        # ---------------------------------------------------------
        # 2. Run hybrid retrieval
        # ---------------------------------------------------------
        try:
            chunks = await self.hybrid_search.search(
                context,
                limit=limit,
            )
        except Exception:
            logger.exception(
                "hybrid_code_retrieval_failed",
                repo_id=context.repo_id,
                limit=limit,
            )

            context.retrieved_chunks = []
            context.early_exit = "EARLY_EXIT_B"
            context.early_exit_message = (
                "Code retrieval failed while searching the repository."
            )
            return

        # ---------------------------------------------------------
        # 3. Store retrieved evidence
        # ---------------------------------------------------------
        context.retrieved_chunks = chunks or []

        # ---------------------------------------------------------
        # 4. Handle empty retrieval
        # ---------------------------------------------------------
        if not context.retrieved_chunks:
            logger.info(
                "no_chunks_retrieved",
                repo_id=context.repo_id,
                query=context.query,
                limit=limit,
            )

            context.early_exit = "EARLY_EXIT_B"
            context.early_exit_message = (
                "No relevant code was found for this query in the "
                "repository. Try rephrasing or broadening your search."
            )
            return

        logger.info(
            "chunks_retrieved",
            repo_id=context.repo_id,
            count=len(context.retrieved_chunks),
            limit=limit,
        )

