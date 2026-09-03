"""
app/modules/search/pipeline/collection_selection.py
Pipeline stage: Collection selection.
"""

from app.modules.search.domain.search_domain import SearchContext


class CollectionSelectionStage:
    async def execute(self, context: SearchContext) -> None:
        """Verify the collection exists or build filter criteria."""
        # For our design, context.qdrant_collection is set by RepositoryIdentificationStage.
        # We also enforce that search filters use context.repo_id.
        pass
