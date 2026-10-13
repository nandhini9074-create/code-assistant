
"""
app/modules/search/pipeline/intent_classification.py

Pipeline stage: Intent Classification (Step 3).

Uses the LLM to classify the user's request into the appropriate
intent and extracts only the parameters explicitly supported by
the classification result.

If the LLM fails, a deterministic code-based fallback is used so
that the search pipeline can continue without depending entirely
on the LLM.

Additional behavior:
    After classification, decide whether a FIX_BUG request requires
    Deep Search and store the decision in context.intent_parameters.

The existing intent classification and fallback logic remain unchanged.
This stage does not set early_exit or alter pipeline execution order.
"""

from __future__ import annotations

import re

from app.core.enums import IntentType
from app.core.logging import get_logger
from app.modules.llm.service.llm_service import LLMService
from app.modules.search.domain.search_domain import SearchContext
from app.modules.search.pipeline.deep_search_decision import (
    decide_deep_search,
)

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

        Deep Search:
            After resolving the intent, decide whether a FIX_BUG
            request requires deeper investigation.

        Deep Search selection does not set early_exit in this stage.
        """

        # Respect an early exit produced by an earlier pipeline stage.
        if context.early_exit:
            logger.info(
                "intent_classification_skipped",
                reason=context.early_exit,
                repo_id=context.repo_id,
            )
            return

        # Preserve the original user query for classification and routing.
        query = str(context.query or "").strip()

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

            fallback_intent = self._fallback_classify_intent(query)

            if fallback_intent is None:
                logger.warning(
                    "intent_classification_code_fallback_unresolved",
                    repo_id=context.repo_id,
                )

                # Preserve existing behavior: do not guess an intent.
                context.intent = None
                context.intent_parameters = {}
                return

            context.intent = fallback_intent
            context.intent_parameters = {}

            self._apply_deep_search_decision(context, query)

            logger.info(
                "intent_classification_code_fallback_complete",
                repo_id=context.repo_id,
                intent=fallback_intent.value,
            )
            return

        # -----------------------------------------------------------
        # Handle an empty LLM result using the existing fallback.
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

            self._apply_deep_search_decision(context, query)

            logger.info(
                "intent_classification_code_fallback_complete",
                repo_id=context.repo_id,
                intent=fallback_intent.value,
            )
            return

        # -----------------------------------------------------------
        # Handle an LLM result without a valid intent.
        # -----------------------------------------------------------
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

            self._apply_deep_search_decision(context, query)

            logger.info(
                "intent_classification_code_fallback_complete",
                repo_id=context.repo_id,
                intent=fallback_intent.value,
            )
            return

        # -----------------------------------------------------------
        # Validate the LLM parameters.
        # -----------------------------------------------------------
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

            self._apply_deep_search_decision(context, query)

            logger.info(
                "intent_classification_code_fallback_complete",
                repo_id=context.repo_id,
                intent=fallback_intent.value,
            )
            return

        # -----------------------------------------------------------
        # Normalize the LLM result to the domain enum.
        # -----------------------------------------------------------
        try:
            context.intent = (
                result.intent
                if isinstance(result.intent, IntentType)
                else IntentType(result.intent)
            )

        except (ValueError, TypeError):
            logger.warning(
                "intent_classification_invalid_intent_using_code_fallback",
                repo_id=context.repo_id,
                intent=str(result.intent),
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

            self._apply_deep_search_decision(context, query)

            logger.info(
                "intent_classification_code_fallback_complete",
                repo_id=context.repo_id,
                intent=fallback_intent.value,
            )
            return

        # -----------------------------------------------------------
        # Successful LLM result.
        # Preserve the original parameters and apply Deep Search
        # routing only when the resolved intent is FIX_BUG.
        # -----------------------------------------------------------
        context.intent_parameters = dict(result.parameters)

        self._apply_deep_search_decision(context, query)

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
    # Deep Search decision — additional behavior for FIX_BUG only
    # ----------------------------------------------------------------
    @staticmethod
    def _apply_deep_search_decision(
        context: SearchContext,
        query: str,
    ) -> None:
        """
        Decide whether an already-classified FIX_BUG request requires
        Deep Search.

        The original query is passed unchanged apart from the trimming
        performed at the start of execute().

        This method does not change the intent, trigger early exit,
        or modify other intents.
        """
        if context.intent != IntentType.FIX_BUG:
            return

        # Diagnostic only: never log the complete query or source code.
        contains_attribute_error = bool(
            re.search(
                r"\bhas\s+no\s+(?:attribute|field|property)\b",
                query,
                flags=re.IGNORECASE,
            )
        )

        logger.info(
            "deep_search_input_diagnostic",
            repo_id=context.repo_id,
            intent=context.intent.value,
            query_length=len(query),
            contains_attribute_error=contains_attribute_error,
        )

        # Use the original user query, not extracted LLM parameters.
        decision = decide_deep_search(
            intent=context.intent.value,
            query=query,
        )

        # Preserve the classification parameters.
        parameters = dict(context.intent_parameters or {})
        parameters["deep_search_requested"] = decision.selected
        parameters["deep_search_reason"] = decision.reason

        context.intent_parameters = parameters

        logger.info(
            "deep_search_decision_completed",
            repo_id=context.repo_id,
            intent=context.intent.value,
            selected=decision.selected,
            reason=decision.reason,
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

        Returns an IntentType when exactly one supported intent matches.
        Returns None when the request is ambiguous or unsupported.

        The fallback does not extract LLM-style parameters.
        """

        normalized_query = query.lower().strip()

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

        # Preserve the existing vulnerability-first classification.
        vuln_patterns = (
            r"\bvulnerab\w*\b",
            r"\baudit\b",
            r"\bcve\b",
            r"\bsecurity\s+(?:vulnerability|issue|flaw|audit|fix)\b",
            r"\bpackage\.json\s+vulnerability\b",
            r"\bpackage\s+vulnerability\b",
        )

        if any(
            re.search(pattern, normalized_query)
            for pattern in vuln_patterns
        ):
            return IntentType.FIX_VULNERABILITY

        matched_intents: list[IntentType] = []

        for intent, intent_patterns in patterns.items():
            if any(
                re.search(pattern, normalized_query)
                for pattern in intent_patterns
            ):
                matched_intents.append(intent)

        # Preserve conservative fallback behavior.
        if len(matched_intents) == 1:
            return matched_intents[0]

        return None
