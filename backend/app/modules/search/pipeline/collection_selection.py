"""Resolve a search source to its existing Qdrant collection."""

from __future__ import annotations

from pathlib import PurePath
from urllib.parse import urlparse

from app.core.logging import get_logger
from app.infrastructure.qdrant.client import get_qdrant_client
from app.modules.search.domain.search_domain import SearchContext

logger = get_logger(__name__)


def clean_name(value: str) -> str:
    """Match the collection-name normalization used by ingestion."""
    return (
        value.strip()
        .lower()
        .replace("-", "_")
        .replace(".", "_")
        .replace("/", "_")
    )


def normalize_source(
    source_type: str,
    source_location: str,
) -> tuple[str, str | None, str]:
    """Return (collection, owner, repository) for a search source."""

    location = source_location.strip()

    if source_type == "git":
        parsed = urlparse(location)
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.netloc.lower() != "github.com"
            or len(parts) != 2
        ):
            raise ValueError("Git source must be a valid GitHub URL")

        owner, repository = parts
        if repository.lower().endswith(".git"):
            repository = repository[:-4]
        if not owner or not repository:
            raise ValueError("Git source must include an owner and repository")

        owner = clean_name(owner)
        repository = clean_name(repository)
        return f"repo_{owner}_{repository}", owner, repository

    if source_type == "zip":
        filename = PurePath(location).name
        if not filename.lower().endswith(".zip"):
            raise ValueError("ZIP source location must end with .zip")

        repository = clean_name(filename[:-4])
        if not repository:
            raise ValueError("ZIP source must include a filename")
        return f"repo_local_{repository}", None, repository

    raise ValueError("Unsupported source type")


class CollectionSelectionStage:
    """Select only the Qdrant collection derived from the request source."""

    async def execute(self, context: SearchContext) -> None:
        if context.early_exit:
            logger.info(
                "collection_selection_skipped",
                reason=context.early_exit,
                source_location=context.source_location,
            )
            return

        if not context.source_type or not context.source_location.strip():
            context.early_exit = "EARLY_EXIT_A"
            context.early_exit_message = (
                "A valid repository source is required for this search."
            )
            return

        try:
            normalized_collection, extracted_owner, extracted_repo = normalize_source(
                context.source_type,
                context.source_location,
            )
        except ValueError as exc:
            context.early_exit = "EARLY_EXIT_A"
            context.early_exit_message = str(exc)
            return

        # Check only the requested collection. Never enumerate all collections.
        try:
            await get_qdrant_client().get_collection(normalized_collection)
        except Exception as exc:
            logger.warning(
                "repository_collection_not_found",
                collection=normalized_collection,
                error=str(exc),
            )
            context.early_exit = "EARLY_EXIT_A"
            context.early_exit_message = (
                f"Repository source '{context.source_location}' is not indexed."
            )
            return

        context.repo_owner = extracted_owner
        context.repo_name = extracted_repo
        context.qdrant_collection = normalized_collection

        logger.info(
            "repository_collection_selected",
            repo_name=context.repo_name,
            repo_owner=context.repo_owner,
            collection=context.qdrant_collection,
        )
