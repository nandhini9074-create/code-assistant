"""
app/modules/search/pipeline/collection_selection.py

Pipeline stage: Collection Selection.

Resolves and selects the target Qdrant collection based on the requested repository.
Each repository has its own collection following the conventions:
    - Remote / GitHub: repo_ownername_repositoryname
    - Local: repo_local_repositoryname

Normalization Rules:
1. If the user provides `ownername_repositoryname` (or `ownername/repositoryname`):
   Normalized to: `repo_ownername_repositoryname`
   Owner and repository details are extracted directly from the `repo_name` input:
     - owner: ownername
     - repository: repositoryname

2. If the user provides only `repositoryname`:
   Normalized to: `repo_local_repositoryname`
   - owner: None
   - repository: repositoryname

Search is performed only against the resolved Qdrant collection.
This stage does not depend on PostgreSQL or RepositoryIdentificationStage.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.infrastructure.qdrant.client import get_qdrant_client
from app.modules.search.domain.search_domain import SearchContext

logger = get_logger(__name__)


def clean_name(val: str) -> str:
    """Normalize a name component by stripping, lowercasing, and replacing hyphens/dots/slashes with underscores."""
    return val.strip().lower().replace("-", "_").replace(".", "_").replace("/", "_")


def parse_and_normalize_repo_input(
    repo_name_input: str,
    available_collections: list[str] | None = None,
) -> tuple[str, str | None, str]:
    """
    Parse the repo_name input and normalize it according to rules:

    1. ownername_repositoryname -> repo_ownername_repositoryname
       (extracts owner: ownername, repo: repositoryname)
    2. repositoryname -> repo_local_repositoryname
       (extracts owner: None, repo: repositoryname)

    Returns:
        (normalized_collection_name, owner, repo_name)
    """
    raw = repo_name_input.strip()

    # Case 1: Slash provided (e.g. owner/repo)
    if "/" in raw:
        parts = raw.split("/", 1)
        owner = clean_name(parts[0])
        repo = clean_name(parts[1])
        collection = f"repo_{owner}_{repo}"
        return collection, owner, repo

    # Clean the input string
    cleaned = clean_name(raw)

    # Case 2: Already prefixed with repo_local_
    if cleaned.startswith("repo_local_"):
        repo = cleaned[len("repo_local_"):]
        return cleaned, None, repo

    # Case 3: Prefixed with local_
    if cleaned.startswith("local_"):
        repo = cleaned[len("local_"):]
        return f"repo_local_{repo}", None, repo

    # Case 4: Already prefixed with repo_
    if cleaned.startswith("repo_"):
        rest = cleaned[len("repo_"):]
        if "_" in rest:
            owner, repo = rest.split("_", 1)
            return cleaned, owner, repo
        else:
            return f"repo_local_{rest}", None, rest

    # Case 5: Plain input without repo_ prefix
    # Could be ownername_repositoryname OR repositoryname
    available_set = (
        {c.lower() for c in available_collections}
        if available_collections is not None
        else set()
    )

    candidate_owner = f"repo_{cleaned}"
    candidate_local = f"repo_local_{cleaned}"

    # If available collections exist, check against them to resolve ambiguity
    if available_set:
        if candidate_owner.lower() in available_set:
            parts = cleaned.split("_", 1)
            owner = parts[0]
            repo = parts[1] if len(parts) > 1 else cleaned
            return candidate_owner, owner, repo

        if candidate_local.lower() in available_set:
            return candidate_local, None, cleaned

    # Fallback when not matched against known collections or collections unavailable:
    # If the input contains an underscore, it is treated as ownername_repositoryname
    if "_" in cleaned:
        owner, repo = cleaned.split("_", 1)
        return candidate_owner, owner, repo
    else:
        return candidate_local, None, cleaned


class CollectionSelectionStage:
    """Selects the Qdrant collection for the current search repository."""

    async def execute(self, context: SearchContext) -> None:
        """
        Configure Qdrant collection selection.

        Behaviour:
        - Skip when an earlier stage triggered an early exit.
        - Validate that the search request contains a repository name.
        - Retrieve all Qdrant collection names.
        - Normalize the requested repo name according to the two supported formats:
            1. ownername_repositoryname -> repo_ownername_repositoryname
            2. repositoryname -> repo_local_repositoryname
        - Extract owner and repository details directly from the repo_name input when
          ownername_repositoryname format is provided. Do not require repo_id.
        - Set context.qdrant_collection to the selected collection.
        - If no collection matches, trigger EARLY_EXIT_A repository not found.
        """

        if context.early_exit:
            logger.info(
                "collection_selection_skipped",
                reason=context.early_exit,
                repo_name=context.repo_name,
            )
            return

        if not context.repo_name or not context.repo_name.strip():
            logger.error(
                "collection_selection_missing_repo_name",
            )
            context.early_exit = "EARLY_EXIT_A"
            context.early_exit_message = (
                "Repository name is required for this search."
            )
            return

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

        # Parse and normalize repo_name input
        normalized_collection, extracted_owner, extracted_repo = (
            parse_and_normalize_repo_input(
                context.repo_name,
                available_collections=collection_names,
            )
        )

        logger.debug(
            "collection_selection_normalized",
            input_repo=context.repo_name,
            normalized_collection=normalized_collection,
            extracted_owner=extracted_owner,
            extracted_repo=extracted_repo,
        )

        # Match against Qdrant collection names (case-insensitive)
        selected_collection = None
        for coll in collection_names:
            if coll.lower() == normalized_collection.lower():
                selected_collection = coll
                break

        if not selected_collection:
            logger.warning(
                "repository_not_found",
                identifier=context.repo_name,
                normalized_collection=normalized_collection,
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
        # EXTRACT OWNER AND REPOSITORY DETAILS DIRECTLY FROM INPUT
        # ---------------------------------------------------------
        context.repo_owner = extracted_owner
        context.repo_name = extracted_repo

        logger.info(
            "repository_collection_selected",
            repo_name=context.repo_name,
            repo_owner=context.repo_owner,
            collection=context.qdrant_collection,
        )