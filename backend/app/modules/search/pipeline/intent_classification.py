
"""
app/modules/search/pipeline/intent_classification.py

Pipeline stage: Intent Classification (Step 3).

Uses the LLM to classify the user's request into the appropriate
intent and extracts only the parameters explicitly supported by
the classification result.
"""

from __future__ import annotations

from app.core.enums import IntentType
from app.core.logging import get_logger
from app.modules.llm.service.llm_service import LLMService
from app.modules.search.domain.search_domain import SearchContext

logger = get_logger(__name__)


class IntentClassificationStage:
    """Pipeline stage responsible for classifying search intent."""

    def __init__(self, llm_service: LLMService) -> None:
        self.llm_service = llm_service

    async def execute(self, context: SearchContext) -> None:
        """
        Classify the user's query and store the validated result
        in SearchContext.

        This stage does not perform retrieval, preprocessing,
        database access, or repository lookup. It only delegates
        classification to LLMService and stores the result.
        """

        # Respect an early exit produced by an earlier pipeline stage.
        if context.early_exit:
            logger.info(
                "intent_classification_skipped",
                reason=context.early_exit,
                repo_id=context.repo_id,
            )
            return

        # Query must exist before classification.
        query = context.query.strip()

        if not query:
            raise ValueError(
                "Cannot classify intent for an empty query."
            )

        logger.info(
            "intent_classification_starting",
            repo_id=context.repo_id,
            query=query,
        )

        # LLMService owns the actual classification logic,
        # validation, and parameter extraction.
        result = await self.llm_service.classify_intent(query)

        if result is None:
            raise ValueError(
                "Intent classification returned no result."
            )

        if result.intent is None:
            raise ValueError(
                "Intent classification returned no intent."
            )

        if not isinstance(result.parameters, dict):
            raise ValueError(
                "Intent classification returned invalid parameters."
            )

        # Normalize the LLM result to the domain enum.
        #
        # The LLM/provider may return:
        #     "ADD_FEATURE"
        #
        # while SearchContext expects:
        #     IntentType.ADD_FEATURE
        #
        # This keeps the shared SearchContext type-safe and allows
        # downstream code to safely use context.intent.value.
        try:
            context.intent = (
                result.intent
                if isinstance(result.intent, IntentType)
                else IntentType(result.intent)
            )
        except ValueError as exc:
            raise ValueError(
                f"Unsupported intent returned by LLM: {result.intent}"
            ) from exc

        context.intent_parameters = result.parameters

        logger.info(
            "intent_classification_complete",
            repo_id=context.repo_id,
            intent=context.intent.value,
            parameter_keys=list(
                context.intent_parameters.keys()
            ),
            confidence=result.confidence,
        )
