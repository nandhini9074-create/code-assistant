
"""
app/modules/search/pipeline/code_analysis.py

Pipeline stage: Intent-Specific Code Analysis (Step 9).

Dispatches code analysis to the analyzer corresponding to the
classified intent and stores the resulting analysis in the
SearchContext.

Validation is handled separately by Step 10.

If the LLM-backed analysis fails, a deterministic fallback result
is stored so the pipeline can continue without inventing analysis.
"""

from __future__ import annotations

from typing import Any

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

        Step 9 only performs analysis. Validation of the generated
        analysis is handled by the separate Step 10 validation stage.

        If the analysis service fails, a deterministic fallback result
        is stored and the pipeline continues.
        """

        # ---------------------------------------------------------
        # Respect pipeline early-exit decisions from previous stages.
        # ---------------------------------------------------------
        if context.early_exit:
            logger.info(
                "code_analysis_stage_skipped",
                reason=context.early_exit,
                repo_id=context.repo_id,
            )
            return

        # ---------------------------------------------------------
        # Step 9 requires a classified intent.
        #
        # Do not stop the pipeline if intent is unavailable.
        # There is no safe way to perform intent-specific analysis,
        # so store an explicit unavailable result instead.
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
        # Preserve existing debugging/output behavior.
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
        # EXISTING ANALYSIS FLOW
        #
        # Do not change analyzer dispatching or CodeAnalysisService
        # behavior. The service remains responsible for selecting
        # the correct analyzer based on context.intent.
        # ---------------------------------------------------------
        try:
            analysis = await self.code_analysis_service.analyze(
                context
            )

        except Exception as exc:
            # -----------------------------------------------------
            # LLM/provider/analyzer failure.
            #
            # Do NOT raise the exception because that would stop
            # the complete search pipeline.
            #
            # Do NOT fabricate analysis.
            # -----------------------------------------------------
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
        # Protect the pipeline from an invalid analyzer response.
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
        # Store the result in the shared pipeline context.
        # ---------------------------------------------------------
        context.analysis_result = analysis

        logger.info(
            "code_analysis_stage_complete",
            intent=context.intent.value,
            repo_id=context.repo_id,
            keys=list(analysis.keys()),
            fallback=(
                analysis.get("analysis_status")
                == "UNAVAILABLE"
            ),
        )

    @staticmethod
    def _build_fallback_analysis(
        context: SearchContext,
        reason: str,
    ) -> dict[str, Any]:
        """
        Build a deterministic analysis result when semantic
        LLM analysis is unavailable.

        This method intentionally does NOT infer:
        - bug causes
        - implementation details
        - optimization opportunities
        - refactoring recommendations
        - code changes

        It only exposes information already present in SearchContext.
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
                context.primary_chunk.metadata
                or {}
            )

            if metadata.get("class_name"):
                target["class_name"] = (
                    metadata.get("class_name")
                )

            if metadata.get("start_line") is not None:
                target["start_line"] = (
                    metadata.get("start_line")
                )

            if metadata.get("end_line") is not None:
                target["end_line"] = (
                    metadata.get("end_line")
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
            "suggestion": None,
            "changes": None,
        }

