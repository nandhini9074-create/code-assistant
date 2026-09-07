
"""
app/modules/search/pipeline/collection_selection.py

Pipeline stage: Collection Selection (Step 5).

Determines the Qdrant collection to use for the current search context.

The project uses a shared Qdrant collection and scopes searches by
repo_id. RepositoryIdentificationStage may populate qdrant_collection;
otherwise the configured default collection is used.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.modules.search.domain.search_domain import SearchContext

logger = get_logger(__name__)


_DEFAULT_COLLECTION = "code_chunks"


class CollectionSelectionStage:
    """Pipeline stage responsible for selecting the Qdrant collection."""

    async def execute(self, context: SearchContext) -> None:
        """
        Select and validate the Qdrant collection for the search.

        Behaviour:
        - Skip when an earlier stage has triggered an early exit.
        - Require a valid repo_id because repository isolation depends
          on it.
        - Preserve a collection already selected by repository
          identification.
        - Otherwise use the configured default collection.
        """

        if context.early_exit:
            logger.info(
                "collection_selection_skipped",
                reason=context.early_exit,
                repo_id=context.repo_id,
            )
            return

        # Repository isolation is required because the default
        # collection may contain chunks from multiple repositories.
        if not context.repo_id:
            logger.error(
                "collection_selection_missing_repo_id",
            )

            context.early_exit = "EARLY_EXIT_A"
            context.early_exit_message = (
                "Could not determine the repository for this search."
            )
            return

        # Preserve the collection selected by RepositoryIdentificationStage.
        if context.qdrant_collection:
            logger.info(
                "collection_selected",
                repo_id=context.repo_id,
                collection=context.qdrant_collection,
            )
            return

        # Shared collection fallback.
        context.qdrant_collection = _DEFAULT_COLLECTION

        logger.warning(
            "collection_selection_fallback",
            repo_id=context.repo_id,
            collection=_DEFAULT_COLLECTION,
        )

