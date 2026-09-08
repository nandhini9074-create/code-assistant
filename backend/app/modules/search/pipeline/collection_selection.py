"""
app/modules/search/pipeline/collection_selection.py

Pipeline stage: Collection Selection.

The current search architecture uses multiple Qdrant collections,
where each repository has its own collection.

Collection names follow the convention:

    repo_owner_repositoryname

For global search, this stage does NOT select a specific collection.
Instead, it marks the search as a global Qdrant search by leaving
context.qdrant_collection as None.

The retrieval layer is responsible for enumerating all Qdrant
collections and searching across them.

This stage does not depend on PostgreSQL or RepositoryIdentificationStage.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.modules.search.domain.search_domain import SearchContext

logger = get_logger(__name__)


class CollectionSelectionStage:
    """Selects the Qdrant search mode for the current search."""

    async def execute(self, context: SearchContext) -> None:
        """
        Configure Qdrant collection selection.

        Behaviour:
        - Skip when an earlier stage triggered an early exit.
        - Validate that the search request contains a repository name.
        - Do NOT select a hardcoded Qdrant collection.
        - Set qdrant_collection to None to indicate global search.
        - The retrieval layer will enumerate all Qdrant collections.

        The repository name is retained in the SearchContext as request
        metadata, but it is NOT used as a Qdrant filter for global search.
        """

        # ---------------------------------------------------------
        # Skip if an earlier stage already stopped the pipeline.
        # ---------------------------------------------------------

        if context.early_exit:
            logger.info(
                "collection_selection_skipped",
                reason=context.early_exit,
                repo_name=context.repo_name,
            )
            return

        # ---------------------------------------------------------
        # Validate repository name.
        # ---------------------------------------------------------

        if not context.repo_name:
            logger.error(
                "collection_selection_missing_repo_name",
            )

            context.early_exit = "EARLY_EXIT_A"
            context.early_exit_message = (
                "Repository name is required for this search."
            )
            return

        # ---------------------------------------------------------
        # Global Qdrant search.
        #
        # Do NOT use:
        #
        #     context.qdrant_collection = "code_chunks"
        #
        # because there is no shared collection.
        #
        # None means the retrieval layer should search ALL
        # repository-specific Qdrant collections.
        # ---------------------------------------------------------

        context.qdrant_collection = None

        logger.info(
            "global_collection_search_selected",
            repo_name=context.repo_name,
        )

        print(
            "[SEARCH] Qdrant search mode: ALL COLLECTIONS"
        )

        print(
            f"[SEARCH] Request repo_name: "
            f"{context.repo_name}"
        )