
"""
app/modules/search/pipeline/code_retrieval.py

Pipeline stage: Code Retrieval.

Generates a query embedding and performs hybrid retrieval against
Qdrant.

The current search architecture uses multiple Qdrant collections,
where each repository has its own collection.

For GLOBAL SEARCH:

    context.qdrant_collection = None

This is a valid search mode.

When qdrant_collection is None, HybridSearch / DenseSearch /
SparseSearch search across all Qdrant collections.

PostgreSQL repository identification is not used during retrieval.
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
            repo_name=context.repo_name,
            query=context.query,
            collection=context.qdrant_collection,
            limit=limit,
            early_exit=context.early_exit,
        )

        print("\n========== CODE RETRIEVAL START ==========")
        print("REPOSITORY:", context.repo_name)
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
                repo_name=context.repo_name,
                reason=context.early_exit,
            )

            print("CODE RETRIEVAL: SKIPPED")
            print("REASON:", context.early_exit)

            return

        # =========================================================
        # VALIDATE REPOSITORY NAME
        # =========================================================

        if not context.repo_name:

            logger.error(
                "code_retrieval_missing_repo_name",
            )

            context.early_exit = "EARLY_EXIT_A"
            context.early_exit_message = (
                "Repository name is required for code retrieval."
            )

            return

        # =========================================================
        # QDRANT COLLECTION MODE
        # =========================================================
        #
        # IMPORTANT:
        #
        # context.qdrant_collection == None is NOT an error.
        #
        # It means GLOBAL SEARCH across all Qdrant collections.
        #
        # Therefore, DO NOT set EARLY_EXIT_A here.
        # =========================================================

        if context.qdrant_collection is None:

            logger.info(
                "code_retrieval_global_qdrant_search",
                repo_name=context.repo_name,
            )

            print(
                "CODE RETRIEVAL: Global Qdrant search enabled"
            )

            print(
                "CODE RETRIEVAL: Searching ALL collections"
            )

        else:

            logger.info(
                "code_retrieval_collection_selected",
                repo_name=context.repo_name,
                collection=context.qdrant_collection,
            )

            print(
                "CODE RETRIEVAL: Searching collection:",
                context.qdrant_collection,
            )

        # =========================================================
        # VALIDATE LIMIT
        # =========================================================

        if limit <= 0:

            logger.error(
                "code_retrieval_invalid_limit",
                repo_name=context.repo_name,
                limit=limit,
            )

            raise ValueError(
                "Code retrieval limit must be greater than zero."
            )

        # =========================================================
        # STEP 1: GENERATE QUERY EMBEDDING
        # =========================================================

        print("\n--- STEP 1: QUERY EMBEDDING ---")

        if context.query_vector is None:

            print("QUERY VECTOR: Not available")
            print("Calling generate_embeddings()...")

            try:

                vectors = await generate_embeddings(
                    [context.query],
                    input_type="query",
                )

                print("generate_embeddings() completed")

                if not vectors:
                    raise ValueError(
                        "Embedding provider returned no vectors."
                    )

                if not vectors[0]:
                    raise ValueError(
                        "Embedding provider returned an empty "
                        "query vector."
                    )

                context.query_vector = vectors[0]

                print(
                    "QUERY VECTOR DIMENSION:",
                    len(context.query_vector),
                )

                print(
                    "QUERY VECTOR FIRST 5:",
                    context.query_vector[:5],
                )

                logger.info(
                    "query_embedding_generated",
                    repo_name=context.repo_name,
                    dimension=len(context.query_vector),
                )

            except Exception as exc:

                # Do not immediately stop the pipeline.
                # HybridSearch may still be able to perform
                # sparse retrieval.

                context.query_vector = None

                logger.exception(
                    "query_embedding_failed",
                    repo_name=context.repo_name,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )

                print("\n[WARNING] QUERY EMBEDDING FAILED")
                print("EXCEPTION TYPE:", type(exc).__name__)
                print("EXCEPTION:", str(exc))
                print(
                    "Continuing with hybrid retrieval..."
                )

        else:

            print("QUERY VECTOR ALREADY EXISTS")

            print(
                "QUERY VECTOR DIMENSION:",
                len(context.query_vector),
            )

            logger.info(
                "query_vector_already_available",
                repo_name=context.repo_name,
                dimension=len(context.query_vector),
            )

        # =========================================================
        # STEP 2: HYBRID / QDRANT SEARCH
        # =========================================================

        print("\n--- STEP 2: QDRANT / HYBRID SEARCH ---")

        print(
            "Repository name:",
            context.repo_name,
        )

        print(
            "Qdrant collection:",
            (
                "ALL COLLECTIONS"
                if context.qdrant_collection is None
                else context.qdrant_collection
            ),
        )

        print(
            "Calling HybridSearch.search()..."
        )

        try:

            chunks = await self.hybrid_search.search(
                context,
                limit=limit,
            )

            if chunks is None:
                chunks = []

            print(
                "HybridSearch.search() completed"
            )

            print(
                "RETRIEVED CHUNKS:",
                len(chunks),
            )

            logger.info(
                "hybrid_search_completed",
                repo_name=context.repo_name,
                collection=context.qdrant_collection,
                result_count=len(chunks),
            )

        except Exception as exc:

            logger.exception(
                "hybrid_code_retrieval_failed",
                repo_name=context.repo_name,
                collection=context.qdrant_collection,
                limit=limit,
                error_type=type(exc).__name__,
                error=str(exc),
            )

            print("\n[ERROR] QDRANT / HYBRID SEARCH FAILED")
            print("EXCEPTION TYPE:", type(exc).__name__)
            print("EXCEPTION:", str(exc))
            print("==========================================\n")

            context.retrieved_chunks = []

            context.early_exit = "EARLY_EXIT_B"

            context.early_exit_message = (
                f"Code retrieval failed: "
                f"{type(exc).__name__}: {str(exc)}"
            )

            return

        # =========================================================
        # STEP 3: STORE RETRIEVAL RESULTS
        # =========================================================

        context.retrieved_chunks = chunks

        print("\n--- STEP 3: RETRIEVAL RESULTS ---")

        print(
            "TOTAL CHUNKS:",
            len(context.retrieved_chunks),
        )

        logger.info(
            "retrieval_results_stored",
            repo_name=context.repo_name,
            result_count=len(context.retrieved_chunks),
        )

        # =========================================================
        # DEBUG: SHOW RETRIEVED CODE
        # =========================================================

        for index, chunk in enumerate(
            context.retrieved_chunks[:5],
            start=1,
        ):

            print(
                f"\n--- RETRIEVED CHUNK {index} ---"
            )

            print(
                "FILE:",
                chunk.file_path,
            )

            print(
                "SCORE:",
                chunk.score,
            )

            print(
                "METADATA:",
                chunk.metadata,
            )

            print(
                "CONTENT PREVIEW:"
            )

            print(
                chunk.content[:500]
            )

        # =========================================================
        # STEP 4: NO RESULTS
        # =========================================================

        if not context.retrieved_chunks:

            print(
                "[WARNING] NO CHUNKS RETRIEVED"
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

            context.early_exit = "EARLY_EXIT_B"

            context.early_exit_message = (
                "No relevant code was found for this query in "
                f"repository '{context.repo_name}'. "
                "Try rephrasing or broadening your search."
            )

            return

        # =========================================================
        # SUCCESS
        # =========================================================

        logger.info(
            "code_retrieval_completed",
            repo_name=context.repo_name,
            collection=context.qdrant_collection,
            result_count=len(context.retrieved_chunks),
        )

        print(
            "\n[OK] CODE RETRIEVAL SUCCESS"
        )

        print(
            "FINAL RETRIEVED CHUNKS:",
            len(context.retrieved_chunks),
        )

        print(
            "========== CODE RETRIEVAL END ==========\n"
        )

