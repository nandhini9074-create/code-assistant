
"""
app/modules/search/pipeline/code_analysis.py

Pipeline stage: Intent-Specific Code Analysis (Step 9).

Dispatches code analysis to the analyzer corresponding to the
classified intent and stores the resulting analysis in SearchContext.

Validation is handled separately by Step 10.

Deep Search owns analysis for requests selected for that workflow.
Normal analysis must not run again after Deep Search has been selected
or has produced a result.

If analysis fails, a deterministic UNAVAILABLE result is stored.
No unsupported cause, patch, or fix is fabricated.
"""

from __future__ import annotations

from typing import Any

from app.core.enums import IntentType
from app.core.logging import get_logger
from app.modules.code_analysis.service.code_analysis_service import (
    CodeAnalysisService,
)
from app.modules.search.domain.search_domain import SearchContext

logger = get_logger(__name__)


class CodeAnalysisStage:
    """Pipeline stage responsible for intent-specific code analysis."""

    def __init__(
        self,
        code_analysis_service: CodeAnalysisService,
    ) -> None:
        self.code_analysis_service = code_analysis_service

    async def execute(self, context: SearchContext) -> None:
        """
        Execute intent-specific code analysis.

        Normal requests use CodeAnalysisService.

        Requests owned by Deep Search must not be analyzed again by
        the normal analyzer. The search service remains responsible
        for selecting and executing the Deep Search workflow.
        """

        # ---------------------------------------------------------
        # Respect early exits from preceding stages.
        # ---------------------------------------------------------
        if context.early_exit:
            logger.info(
                "code_analysis_stage_skipped",
                reason=context.early_exit,
                repo_id=context.repo_id,
            )
            return

        # ---------------------------------------------------------
        # Deep Search requests: If deep search produced context,
        # proceed with normal analysis (e.g. FixBugAnalyzer).
        # Only fallback if no context was produced.
        # ---------------------------------------------------------
        parameters = context.intent_parameters or {}

        deep_search_selected = (
            context.intent == IntentType.FIX_BUG
            and isinstance(parameters, dict)
            and parameters.get("deep_search_requested") is True
        )

        deep_search_result = getattr(
            context,
            "deep_search_result",
            None,
        )

        if (deep_search_selected or deep_search_result is not None) and not context.llm_context and not context.retrieved_chunks:
            logger.info(
                "code_analysis_fallback_deep_search_empty",
                repo_id=context.repo_id,
                deep_search_selected=deep_search_selected,
                deep_search_result_available=(
                    deep_search_result is not None
                ),
            )

            context.analysis_result = (
                self._build_fallback_analysis(
                    context,
                    reason=(
                        "This FIX_BUG request is assigned to "
                        "Deep Search, but no code context was retrieved "
                        "for code analysis."
                    ),
                )
            )
            return

        # ---------------------------------------------------------
        # A classified intent is required for normal analysis.
        # ---------------------------------------------------------
        if context.intent is None:
            logger.warning(
                "code_analysis_intent_unavailable",
                repo_id=context.repo_id,
            )

            context.analysis_result = (
                self._build_fallback_analysis(
                    context,
                    reason=(
                        "Code analysis could not be performed because "
                        "the request intent was not classified."
                    ),
                )
            )
            return

        logger.info(
            "code_analysis_stage_starting",
            intent=context.intent.value,
            repo_id=context.repo_id,
        )

        # ---------------------------------------------------------
        # Preserve the existing debugging output.
        # ---------------------------------------------------------
        print("\n" + "=" * 80)
        print("LLM INPUT")
        print("=" * 80)

        print("\nQUERY:")
        print(context.query)

        print("\nCODE CONTEXT:")
        print(context.llm_context or "EMPTY")

        print("=" * 80 + "\n")

        # ---------------------------------------------------------
        # Normal intent-specific analysis.
        # ---------------------------------------------------------
        try:
            analysis = await self.code_analysis_service.analyze(
                context
            )

        except Exception as exc:
            logger.exception(
                "code_analysis_failed_using_fallback",
                intent=context.intent.value,
                repo_id=context.repo_id,
                error_type=type(exc).__name__,
            )

            analysis = self._build_fallback_analysis(
                context,
                reason=(
                    "Code analysis was unavailable because the "
                    "analysis service failed. The retrieved code "
                    "context is preserved, but no semantic analysis "
                    "or code-change recommendation was generated."
                ),
            )

        # ---------------------------------------------------------
        # Reject invalid analyzer results.
        # ---------------------------------------------------------
        if not isinstance(analysis, dict):
            logger.warning(
                "code_analysis_invalid_result_using_fallback",
                intent=context.intent.value,
                repo_id=context.repo_id,
                result_type=type(analysis).__name__,
            )

            analysis = self._build_fallback_analysis(
                context,
                reason=(
                    "Code analysis returned an invalid result. "
                    "No semantic analysis or code-change "
                    "recommendation was generated."
                ),
            )

        # ---------------------------------------------------------
        # Normalize error-shaped analyzer results.
        #
        # Do not send an error-shaped analysis into downstream
        # validation as if it were a successful recommendation.
        # ---------------------------------------------------------
        elif analysis.get("error"):
            logger.warning(
                "code_analysis_llm_failed_using_fallback",
                intent=context.intent.value,
                repo_id=context.repo_id,
                error_type="AnalyzerErrorResult",
            )

            analysis = self._build_fallback_analysis(
                context,
                reason=(
                    "Code analysis was unavailable because the "
                    "analyzer reported an error. No verified fix "
                    "was generated."
                ),
            )

        # ---------------------------------------------------------
        # Normalize explicitly unavailable analyzer responses.
        #
        # Keep analyzer-specific evidence and diagnostics, but
        # prevent downstream stages from treating an unavailable
        # analysis as a successful patch proposal.
        # ---------------------------------------------------------
        elif (
            str(analysis.get("analysis_status", ""))
            .strip()
            .upper()
            == "UNAVAILABLE"
        ):
            analysis = dict(analysis)
            analysis["analysis_status"] = "UNAVAILABLE"
            analysis["suggested_code"] = ""
            analysis["code_change"] = None

            # Do not erase the analyzer's evidence_summary,
            # reason, or other diagnostic fields.

        # ---------------------------------------------------------
        # Store the result in the shared pipeline context.
        # ---------------------------------------------------------
        context.analysis_result = analysis

        logger.info(
            "code_analysis_stage_complete",
            intent=context.intent.value,
            repo_id=context.repo_id,
            keys=list(analysis.keys()),
            fallback=(
                str(
                    analysis.get("analysis_status", "")
                ).upper()
                == "UNAVAILABLE"
            ),
        )

    @staticmethod
    def _build_fallback_analysis(
        context: SearchContext,
        reason: str,
    ) -> dict[str, Any]:
        """
        Build a deterministic unavailable analysis.

        Only information already present in SearchContext is exposed.

        This method does not infer bug causes, implementation details,
        optimizations, refactoring recommendations, or code changes.
        """

        target = None

        if context.target_symbol:
            target = {
                "symbol": context.target_symbol,
            }

        if context.primary_chunk:
            target = target or {}

            target["file_path"] = (
                context.primary_chunk.file_path
            )

            metadata = (
                context.primary_chunk.metadata or {}
            )

            if metadata.get("class_name"):
                target["class_name"] = (
                    metadata["class_name"]
                )

            if metadata.get("start_line") is not None:
                target["start_line"] = (
                    metadata["start_line"]
                )

            if metadata.get("end_line") is not None:
                target["end_line"] = (
                    metadata["end_line"]
                )

        return {
            "analysis_status": "UNAVAILABLE",
            "analysis_available": False,
            "reason": reason,
            "intent": (
                context.intent.value
                if context.intent is not None
                else None
            ),
            "query": context.query,
            "target": target,
            "code_context_available": bool(
                context.llm_context
            ),
            "code_context": (
                context.llm_context
                if context.llm_context
                else None
            ),
            # Never present a generic recommendation as a verified fix.
            "suggestion": "",
            "proposed_change": "",
            "suggested_code": "",
            "code_change": None,
            "fallback_confidence": "low",
        }
