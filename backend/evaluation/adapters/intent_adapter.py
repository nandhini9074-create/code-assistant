"""
evaluation/adapters/intent_adapter.py
Adapter wrapping production intent classification components for evaluation.
"""

from __future__ import annotations

from typing import Optional

from app.core.enums import IntentType
from app.core.logging import get_logger
from app.modules.search.domain.search_domain import SearchContext
from app.modules.search.pipeline.intent_classification import IntentClassificationStage
from evaluation.adapters.base import BaseIntentAdapter
from evaluation.exceptions import AdapterError

logger = get_logger(__name__)


class ProductionIntentAdapter(BaseIntentAdapter):
    """
    Adapts the production IntentClassificationStage for benchmark evaluation.
    Can operate in standard mode (calling LLM with fallback) or deterministic-only
    mode (offline testing using production fallback keyword rules).
    """

    def __init__(
        self,
        stage: Optional[IntentClassificationStage] = None,
        deterministic_only: bool = False,
    ) -> None:
        self.stage = stage
        self.deterministic_only = deterministic_only

    async def classify(
        self, query: str, repo_name: Optional[str] = None
    ) -> Optional[IntentType]:
        """
        Execute intent classification for the given query using existing production logic.
        """
        clean_query = query.strip()
        if not clean_query:
            return None

        # Deterministic / offline evaluation path (zero external API calls)
        if self.deterministic_only:
            return IntentClassificationStage._fallback_classify_intent(clean_query)

        # Full pipeline stage path
        if self.stage is not None:
            context = SearchContext(
                query=clean_query,
                repo_name=repo_name,
            )
            try:
                await self.stage.execute(context)
                return context.intent
            except Exception as exc:
                logger.warning(
                    "intent_adapter_stage_execution_failed",
                    query=clean_query,
                    error=str(exc),
                )
                # Fallback to deterministic classifier on error
                return IntentClassificationStage._fallback_classify_intent(clean_query)

        # If no stage was injected, use the production fallback classifier directly
        return IntentClassificationStage._fallback_classify_intent(clean_query)
