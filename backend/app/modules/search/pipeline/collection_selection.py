
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
from app.infrastructure.qdrant.client import get_qdrant_client
from app.modules.search.domain.search_domain import SearchContext

logger = get_logger(__name__)


class CollectionSelectionStage:
    """Selects the Qdrant collection for the current search repository."""

    async def execute(self, context: SearchContext) -> None:
        """
        Configure Qdrant collection selection.

        Behaviour:
        - Skip when an earlier stage triggered an early exit.
        - Validate that the search request contains a repository name.
        - Retrieve all Qdrant collection names.
        - Normalize the requested repo name by replacing '-' with '_'.
        - Find the collection whose name contains the normalized repo name.
        - Set context.qdrant_collection to the selected collection.
        - Extract the repository owner from the selected collection name.
        - If no collection matches, trigger EARLY_EXIT_A repository not found.
        """

        if context.early_exit:
            logger.info(
                "collection_selection_skipped",
                reason=context.early_exit,
                repo_name=context.repo_name,
            )
            return

        if not context.repo_name:
            logger.error(
                "collection_selection_missing_repo_name",
            )
            context.early_exit = "EARLY_EXIT_A"
            context.early_exit_message = (
                "Repository name is required for this search."
            )
            return

        normalized_repo_name = context.repo_name.replace("-", "_")

        logger.debug(
            "collection_selection_normalizing",
            repo_name=context.repo_name,
            normalized=normalized_repo_name,
        )

        client = get_qdrant_client()

        try:
            collections_response = await client.get_collections()

            collection_names = [
                collection.name
                for collection in collections_response.collections
            ]

        except Exception as exc:
            logger.exception(
                "collection_selection_get_collections_failed",
                error=str(exc),
            )
            collection_names = []

        selected_collection = None

        for coll in collection_names:
            if normalized_repo_name in coll:
                selected_collection = coll
                break

        if not selected_collection:
            target = normalized_repo_name.split("/")[-1].lower()

            for coll in collection_names:
                if (
                    normalized_repo_name.lower() in coll.lower()
                    or target in coll.lower()
                ):
                    selected_collection = coll
                    break

        if not selected_collection:
            logger.warning(
                "repository_not_found",
                identifier=context.repo_name,
            )

            context.early_exit = "EARLY_EXIT_A"

            context.early_exit_message = (
                f"Repository '{context.repo_name}' could not be found. "
                "Please clarify which repository should be analysed."
            )

            return

        # ---------------------------------------------------------
        # SELECT QDRANT COLLECTION
        # ---------------------------------------------------------

        context.qdrant_collection = selected_collection

        # ---------------------------------------------------------
        # EXTRACT REPOSITORY OWNER
        #
        # Collection format:
        #
        # repo_<owner>_<repository_name>
        #
        # Example:
        # repo_nandhini9074_create_demo10_transaction
        #
        # Result:
        # context.repo_owner = "nandhini9074"
        #
        # split("_", 2) ensures everything after the owner is
        # preserved as the repository-name portion.
        # ---------------------------------------------------------

        if selected_collection.startswith("repo_"):
            collection_parts = selected_collection.split("_", 2)

            if len(collection_parts) == 3:
                context.repo_owner = collection_parts[1]


        logger.info(
            "repository_collection_selected",
            repo_name=context.repo_name,
            repo_owner=context.repo_owner,
            normalized_repo_name=normalized_repo_name,
            collection=selected_collection,
        )

