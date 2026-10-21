"""
evaluation/adapters/base.py
Abstract adapter interfaces for intent classification and code retrieval components.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from app.core.enums import IntentType
from app.modules.search.domain.search_domain import RetrievedChunk


class BaseIntentAdapter(ABC):
    """Abstract interface for evaluating intent classification systems."""

    @abstractmethod
    async def classify(
        self, query: str, repo_name: Optional[str] = None
    ) -> Optional[IntentType]:
        """
        Classify the intent of a search query.

        Args:
            query: The natural language search query.
            repo_name: Optional repository context.

        Returns:
            The classified IntentType, or None if unresolved.
        """


class BaseRetrieverAdapter(ABC):
    """Abstract interface for evaluating code retrieval engines."""

    @abstractmethod
    async def retrieve(
        self,
        query: str,
        collection_name: str,
        limit: int = 20,
        repo_name: Optional[str] = None,
    ) -> List[RetrievedChunk]:
        """
        Retrieve code chunks relevant to a query.

        Args:
            query: The search query text.
            collection_name: Qdrant collection name to retrieve from.
            limit: Maximum number of chunks to return.
            repo_name: Optional repository name for context.

        Returns:
            List of RetrievedChunk instances.
        """
