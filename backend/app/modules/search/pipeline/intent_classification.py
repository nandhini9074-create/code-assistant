
"""
app/modules/search/pipeline/intent_classification.py

Pipeline stage: Intent Classification (Step 3).

Uses the LLM to classify the user's request into the appropriate
intent and extracts only the parameters explicitly supported by
the classification result.

If the LLM fails, a deterministic code-based fallback is used so
that the search pipeline can continue without depending entirely
on the LLM.
"""

from __future__ import annotations

import re

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

        Normal flow:
            LLMService -> validated intent -> continue pipeline

        Fallback flow:
            LLM failure -> deterministic code classification
            -> continue pipeline

        The fallback never fabricates an intent. If the intent cannot
        be determined safely, the stage leaves the intent unset and
        allows the pipeline to continue.
        """

        # -----------------------------------------------------------
        # Respect an early exit produced by an earlier pipeline stage.
        # -----------------------------------------------------------
        if context.early_exit:
            logger.info(
                "intent_classification_skipped",
                reason=context.early_exit,
                repo_id=context.repo_id,
            )
            return

        # -----------------------------------------------------------
        # Query must exist before classification.
        # -----------------------------------------------------------
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

        # -----------------------------------------------------------
        # Primary path: LLM classification
        # -----------------------------------------------------------
        try:
            result = await self.llm_service.classify_intent(query)

        except Exception as exc:
            logger.warning(
                "intent_classification_llm_failed_using_code_fallback",
                repo_id=context.repo_id,
                error=str(exc),
            )

            # -------------------------------------------------------
            # Fallback: deterministic code-based classification
            # -------------------------------------------------------
            fallback_intent = self._fallback_classify_intent(query)

            if fallback_intent is None:
                logger.warning(
                    "intent_classification_code_fallback_unresolved",
                    repo_id=context.repo_id,
                )

                # Do not guess an intent.
                #
                # The important requirement here is that the pipeline
                # must not stop only because the LLM failed.
                context.intent = None
                context.intent_parameters = {}

                return

            context.intent = fallback_intent
            context.intent_parameters = {}

            logger.info(
                "intent_classification_code_fallback_complete",
                repo_id=context.repo_id,
                intent=fallback_intent.value,
            )

            return

        # -----------------------------------------------------------
        # Validate successful LLM result
        # -----------------------------------------------------------
        if result is None:
            logger.warning(
                "intent_classification_empty_llm_result_using_code_fallback",
                repo_id=context.repo_id,
            )

            fallback_intent = self._fallback_classify_intent(query)

            if fallback_intent is None:
                context.intent = None
                context.intent_parameters = {}

                logger.warning(
                    "intent_classification_code_fallback_unresolved",
                    repo_id=context.repo_id,
                )

                return

            context.intent = fallback_intent
            context.intent_parameters = {}

            logger.info(
                "intent_classification_code_fallback_complete",
                repo_id=context.repo_id,
                intent=fallback_intent.value,
            )

            return

        if result.intent is None:
            logger.warning(
                "intent_classification_llm_missing_intent_using_code_fallback",
                repo_id=context.repo_id,
            )

            fallback_intent = self._fallback_classify_intent(query)

            if fallback_intent is None:
                context.intent = None
                context.intent_parameters = {}

                logger.warning(
                    "intent_classification_code_fallback_unresolved",
                    repo_id=context.repo_id,
                )

                return

            context.intent = fallback_intent
            context.intent_parameters = {}

            logger.info(
                "intent_classification_code_fallback_complete",
                repo_id=context.repo_id,
                intent=fallback_intent.value,
            )

            return

        if not isinstance(result.parameters, dict):
            logger.warning(
                "intent_classification_invalid_parameters_using_code_fallback",
                repo_id=context.repo_id,
            )

            fallback_intent = self._fallback_classify_intent(query)

            if fallback_intent is None:
                context.intent = None
                context.intent_parameters = {}

                logger.warning(
                    "intent_classification_code_fallback_unresolved",
                    repo_id=context.repo_id,
                )

                return

            context.intent = fallback_intent
            context.intent_parameters = {}

            logger.info(
                "intent_classification_code_fallback_complete",
                repo_id=context.repo_id,
                intent=fallback_intent.value,
            )

            return

        # -----------------------------------------------------------
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
        # -----------------------------------------------------------
        try:
            context.intent = (
                result.intent
                if isinstance(result.intent, IntentType)
                else IntentType(result.intent)
            )

        except ValueError:
            logger.warning(
                "intent_classification_invalid_intent_using_code_fallback",
                repo_id=context.repo_id,
                intent=result.intent,
            )

            fallback_intent = self._fallback_classify_intent(query)

            if fallback_intent is None:
                context.intent = None
                context.intent_parameters = {}

                logger.warning(
                    "intent_classification_code_fallback_unresolved",
                    repo_id=context.repo_id,
                )

                return

            context.intent = fallback_intent
            context.intent_parameters = {}

            logger.info(
                "intent_classification_code_fallback_complete",
                repo_id=context.repo_id,
                intent=fallback_intent.value,
            )

            return

        # -----------------------------------------------------------
        # Successful LLM result
        # -----------------------------------------------------------
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

    # ----------------------------------------------------------------
    # Deterministic fallback
    # ----------------------------------------------------------------
    @staticmethod
    def _fallback_classify_intent(
        query: str,
    ) -> IntentType | None:
        """
        Determine intent using deterministic keyword matching.

        This method is intentionally conservative.

        Returns:
            IntentType:
                When exactly one intent can be identified safely.

            None:
                When the query is ambiguous or no supported intent
                can be determined.

        The fallback does not attempt to extract LLM-style parameters.
        It only provides the minimum information required to keep
        the pipeline moving.
        """

        normalized_query = query.lower().strip()

        # -----------------------------------------------------------
        # Intent patterns
        # -----------------------------------------------------------
        patterns: dict[IntentType, tuple[str, ...]] = {
            IntentType.RETRIEVE: (
                r"\bfind\b",
                r"\bget\b",
                r"\bretrieve\b",
                r"\bshow\b",
                r"\blocate\b",
                r"\bsearch\b",
                r"\blist\b",
                r"\bwhere\b",
                r"\bidentify\b",
                r"\bfetch\b",
            ),
            IntentType.ADD_FEATURE: (
                r"\badd\b",
                r"\bcreate\b",
                r"\bimplement\b",
                r"\bintroduce\b",
                r"\bsupport\b",
                r"\bnew feature\b",
            ),
            IntentType.FIX_BUG: (
                r"\bfix\b",
                r"\bbug\b",
                r"\berror\b",
                r"\bissue\b",
                r"\bdebug\b",
                r"\bbroken\b",
                r"\bnot working\b",
            ),
            IntentType.OPTIMIZE: (
                r"\boptimize\b",
                r"\boptimise\b",
                r"\boptimization\b",
                r"\boptimisation\b",
                r"\bimprove performance\b",
                r"\bspeed up\b",
                r"\bfaster\b",
                r"\bperformance\b",
            ),
            IntentType.REFACTOR: (
                r"\brefactor\b",
                r"\brefactoring\b",
                r"\brestructure\b",
                r"\bclean up\b",
                r"\bcleanup\b",
                r"\breorganize\b",
                r"\breorganise\b",
            ),
        }

        # -----------------------------------------------------------
        # Find matching intents
        # -----------------------------------------------------------
        matched_intents: list[IntentType] = []

        for intent, intent_patterns in patterns.items():
            if any(
                re.search(pattern, normalized_query)
                for pattern in intent_patterns
            ):
                matched_intents.append(intent)

        # -----------------------------------------------------------
        # Conservative behavior:
        #
        # Exactly one match -> safe fallback.
        #
        # Multiple matches -> ambiguous.
        #
        # No matches -> unknown.
        # -----------------------------------------------------------
        if len(matched_intents) == 1:
            return matched_intents[0]

        if len(matched_intents) > 1:
            return None

        return None
