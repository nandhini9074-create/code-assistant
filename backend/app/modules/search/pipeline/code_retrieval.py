
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

        logger.info(
            "code_retrieval_started",
            repo_id=context.repo_id,
            query=context.query,
            collection=context.qdrant_collection,
            limit=limit,
            early_exit=context.early_exit,
        )

        print("\n========== CODE RETRIEVAL START ==========")
        print("REPO ID:", context.repo_id)
        print("QUERY:", context.query)
        print("COLLECTION:", context.qdrant_collection)
        print("LIMIT:", limit)
        print("EARLY EXIT:", context.early_exit)

        # =========================================================
        # EARLY EXIT CHECK
        # =========================================================

        if context.early_exit:

            logger.info(
                "code_retrieval_skipped",
                repo_id=context.repo_id,
                reason=context.early_exit,
            )

            print("CODE RETRIEVAL: SKIPPED")
            print("REASON:", context.early_exit)
            return

        if limit <= 0:

            logger.error(
                "code_retrieval_invalid_limit",
                repo_id=context.repo_id,
                limit=limit,
            )

            raise ValueError(
                "Code retrieval limit must be greater than zero."
            )

        # =========================================================
        # 1. GENERATE QUERY EMBEDDING
        # =========================================================

        logger.info(
            "query_embedding_started",
            repo_id=context.repo_id,
            query=context.query,
        )

        print("\n--- STEP 1: QUERY EMBEDDING ---")

        if context.query_vector is None:

            logger.info(
                "query_vector_missing",
                repo_id=context.repo_id,
            )

            print("QUERY VECTOR: Not available")
            print("Calling generate_embeddings()...")

            try:

                vectors = await generate_embeddings(
                    [context.query],
                    input_type="query",
                )

                logger.info(
                    "query_embedding_provider_completed",
                    repo_id=context.repo_id,
                    vectors_count=len(vectors) if vectors else 0,
                )

                print("generate_embeddings() completed")
                print("VECTORS TYPE:", type(vectors))

                if vectors:

                    print("NUMBER OF VECTORS:", len(vectors))

                    if vectors[0]:

                        logger.info(
                            "query_embedding_generated",
                            repo_id=context.repo_id,
                            dimension=len(vectors[0]),
                        )

                        print(
                            "QUERY VECTOR DIMENSION:",
                            len(vectors[0]),
                        )

                        print(
                            "QUERY VECTOR FIRST 5:",
                            vectors[0][:5],
                        )

                if not vectors or not vectors[0]:

                    logger.error(
                        "query_embedding_empty",
                        repo_id=context.repo_id,
                    )

                    raise ValueError(
                        "Embedding provider returned no query vector."
                    )

                context.query_vector = vectors[0]

                logger.info(
                    "query_embedding_stored_in_context",
                    repo_id=context.repo_id,
                    dimension=len(context.query_vector),
                )

            except Exception as exc:

                logger.warning(
                    "query_embedding_failed_fallback_sparse",
                    repo_id=context.repo_id,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )

                print("\n[!] QUERY EMBEDDING FAILED - Falling back to sparse retrieval")
                print("EXCEPTION TYPE:", type(exc).__name__)
                print("EXCEPTION:", str(exc))
                print("==========================================\n")

                context.query_vector = None

        else:

            logger.info(
                "query_vector_already_available",
                repo_id=context.repo_id,
                dimension=len(context.query_vector),
            )

            print("QUERY VECTOR ALREADY EXISTS")
            print(
                "QUERY VECTOR DIMENSION:",
                len(context.query_vector),
            )

        # =========================================================
        # 2. HYBRID SEARCH
        # =========================================================

        logger.info(
            "hybrid_search_started",
            repo_id=context.repo_id,
            collection=context.qdrant_collection,
            limit=limit,
        )

        print("\n--- STEP 2: HYBRID SEARCH ---")
        print("Calling HybridSearch.search()...")

        try:

            chunks = await self.hybrid_search.search(
                context,
                limit=limit,
            )

            logger.info(
                "hybrid_search_completed",
                repo_id=context.repo_id,
                result_count=len(chunks or []),
            )

            print("HybridSearch.search() completed")
            print("RETRIEVED CHUNKS:", len(chunks or []))

        except Exception as exc:

            logger.exception(
                "hybrid_code_retrieval_failed",
                repo_id=context.repo_id,
                limit=limit,
                error_type=type(exc).__name__,
                error=str(exc),
            )

            print("\n[ERROR] HYBRID SEARCH FAILED")
            print("EXCEPTION TYPE:", type(exc).__name__)
            print("EXCEPTION:", str(exc))
            print("==========================================\n")

            context.retrieved_chunks = []
            context.early_exit = "EARLY_EXIT_B"
            context.early_exit_message = (
                f"Code retrieval failed: "
                f"{type(exc).__name__}: {str(exc)}"
            )

            logger.warning(
                "code_retrieval_early_exit",
                repo_id=context.repo_id,
                early_exit=context.early_exit,
                message=context.early_exit_message,
            )

            return

        # =========================================================
        # 3. STORE RETRIEVAL RESULTS
        # =========================================================

        context.retrieved_chunks = chunks or []

        logger.info(
            "retrieval_results_stored",
            repo_id=context.repo_id,
            result_count=len(context.retrieved_chunks),
        )

        print("\n--- STEP 3: RETRIEVAL RESULTS ---")
        print("TOTAL CHUNKS:", len(context.retrieved_chunks))

        # =========================================================
        # NO RESULTS
        # =========================================================

        if not context.retrieved_chunks:

            logger.warning(
                "no_chunks_retrieved",
                repo_id=context.repo_id,
                query=context.query,
                limit=limit,
            )

            print("[!] NO CHUNKS RETRIEVED")

            context.early_exit = "EARLY_EXIT_B"
            context.early_exit_message = (
                "No relevant code was found for this query in the "
                "repository. Try rephrasing or broadening your search."
            )

            logger.warning(
                "code_retrieval_early_exit",
                repo_id=context.repo_id,
                early_exit=context.early_exit,
                message=context.early_exit_message,
            )

            return

        # =========================================================
        # SUCCESS
        # =========================================================

        logger.info(
            "code_retrieval_completed",
            repo_id=context.repo_id,
            result_count=len(context.retrieved_chunks),
        )

        print("[OK] CODE RETRIEVAL SUCCESS")

        print("========== CODE RETRIEVAL END ==========\n")

