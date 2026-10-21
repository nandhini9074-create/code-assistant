"""
evaluation/adapters/retriever_adapter.py
Adapter wrapping production code retrieval stages for evaluation.
"""

from __future__ import annotations

from typing import List, Optional

from app.core.logging import get_logger
from app.modules.search.domain.search_domain import RetrievedChunk, SearchContext
from app.modules.search.pipeline.code_retrieval import CodeRetrievalStage
from evaluation.adapters.base import BaseRetrieverAdapter
from evaluation.exceptions import AdapterError

logger = get_logger(__name__)


class ProductionRetrieverAdapter(BaseRetrieverAdapter):
    """
    Adapts the production CodeRetrievalStage for benchmark retrieval evaluation.
    Delegates to the existing hybrid retrieval engine against Qdrant without altering
    production search code.
    """

    def __init__(self, stage: CodeRetrievalStage) -> None:
        self.stage = stage

    async def retrieve(
        self,
        query: str,
        collection_name: str,
        limit: int = 20,
        repo_name: Optional[str] = None,
    ) -> List[RetrievedChunk]:
        """
        Execute code retrieval for the given query and collection.
        """
        clean_query = query.strip()
        if not clean_query:
            return []

        resolved_repo_name = repo_name or collection_name

        context = SearchContext(
            query=clean_query,
            repo_name=resolved_repo_name,
            qdrant_collection=collection_name,
        )

        try:
            await self.stage.execute(context, limit=limit)
            return list(context.retrieved_chunks)
        except Exception as exc:
            logger.error(
                "retriever_adapter_execution_failed",
                query=clean_query,
                collection=collection_name,
                error=str(exc),
            )
            raise AdapterError(
                f"Failed to retrieve chunks for query '{clean_query}': {exc}",
                adapter_name="ProductionRetrieverAdapter",
                details={"query": clean_query, "collection": collection_name},
            ) from exc
