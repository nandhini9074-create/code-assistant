
"""
app/modules/search/pipeline/evidence_validation.py

Pipeline stage: Validation (Step 10).

Executes multi-layer validation (Evidence, Code Existence, Suggestion consistency)
on the Step 9 analysis result. If invalid, executes up to 2 retries with validation feedback.

If still invalid after 2 retries, triggers Early Exit D.

When Step 9 analysis is unavailable because the LLM failed, validation
uses a deterministic fallback so the pipeline can continue without
inventing validation results.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.modules.code_analysis.service.code_analysis_service import (
    CodeAnalysisService,
)
from app.modules.search.domain.search_domain import SearchContext

logger = get_logger(__name__)

MAX_VALIDATION_RETRIES = 2


class EvidenceValidationStage:
    """Pipeline stage responsible for validating code analysis."""

    def __init__(
        self,
        code_analysis_service: CodeAnalysisService,
    ) -> None:
        self.code_analysis_service = code_analysis_service

    async def execute(self, context: SearchContext) -> None:
        """
        Validate Step 9 code analysis against retrieved evidence chunks.

        Normal validation and retry behavior is preserved.

        If Step 9 analysis is marked as unavailable because the LLM
        failed, deterministic validation is used instead so the
        pipeline can continue without generating unsupported claims.
        """

        if context.early_exit:
            logger.info(
                "evidence_validation_skipped",
                reason=context.early_exit,
                repo_id=context.repo_id,
            )
            return

        analysis = context.analysis_result or {}

        # ---------------------------------------------------------
        # Deterministic fallback for unavailable Step 9 analysis.
        # ---------------------------------------------------------
        #
        # Do not attempt LLM validation/re-analysis when Step 9
        # explicitly reports that analysis is unavailable.
        #
        # The fallback does NOT claim that the analysis is correct.
        # It only records that validation could not be performed.
        #
        if analysis.get("analysis_status") == "UNAVAILABLE":
            self._apply_unavailable_fallback(context, analysis)
            return

        retry_count = 0

        while True:
            try:
                val_result = self.code_analysis_service.validate_analysis(
                    analysis,
                    context.retrieved_chunks,
                )
            except Exception as exc:
                logger.warning(
                    "validation_service_failed",
                    repo_id=context.repo_id,
                    error=str(exc),
                )

                self._apply_validation_fallback(
                    context=context,
                    analysis=analysis,
                    reason=f"Validation service unavailable: {exc}",
                )
                return

            if val_result is None:
                self._apply_validation_fallback(
                    context=context,
                    analysis=analysis,
                    reason="Validation service returned no result.",
                )
                return

            if val_result.is_valid:
                context.validated = True
                context.validation_status = "passed"
                context.validation_errors = []
                context.validation_retries = retry_count

                logger.info(
                    "validation_passed",
                    repo_id=context.repo_id,
                    retries=retry_count,
                )
                return

            logger.warning(
                "validation_failed_attempt",
                errors=val_result.errors,
                retry_count=retry_count,
                max_retries=MAX_VALIDATION_RETRIES,
                repo_id=context.repo_id,
            )

            if retry_count < MAX_VALIDATION_RETRIES:
                retry_count += 1
                context.validation_retries = retry_count
                context.validation_feedback = val_result.errors

                # Re-run Step 9 with validation feedback passed
                # to the analyzer.
                try:
                    regenerated = await self.code_analysis_service.analyze(
                        context
                    )

                    if isinstance(regenerated, dict):
                        analysis = regenerated
                        context.analysis_result = regenerated
                    else:
                        self._apply_validation_fallback(
                            context=context,
                            analysis=analysis,
                            reason=(
                                "Code analysis retry returned an invalid result."
                            ),
                        )
                        return

                except Exception as exc:
                    logger.warning(
                        "code_analysis_retry_failed",
                        repo_id=context.repo_id,
                        retry_count=retry_count,
                        error=str(exc),
                    )

                    self._apply_validation_fallback(
                        context=context,
                        analysis=analysis,
                        reason=(
                            f"Code analysis retry unavailable: {exc}"
                        ),
                    )
                    return

            else:
                # Exhausted maximum retries -> Trigger Early Exit D.
                context.validated = False
                context.validation_status = "failed"
                context.validation_errors = val_result.errors
                context.early_exit = "EARLY_EXIT_D"
                context.early_exit_message = (
                    f"Code analysis failed validation after "
                    f"{MAX_VALIDATION_RETRIES} retries: "
                    + "; ".join(val_result.errors)
                )

                logger.warning(
                    "early_exit_d_triggered",
                    repo_id=context.repo_id,
                    errors=val_result.errors,
                )
                return

    @staticmethod
    def _apply_unavailable_fallback(
        context: SearchContext,
        analysis: dict,
    ) -> None:
        """
        Deterministic validation fallback for unavailable analysis.

        This does not mark unavailable analysis as valid. It records
        that validation could not be performed while allowing later
        pipeline stages to execute.
        """

        context.validated = False
        context.validation_status = "unavailable"
        context.validation_errors = [
            "Code analysis was unavailable; validation could not be performed."
        ]
        context.validation_retries = 0
        context.validation_feedback = []

        logger.warning(
            "validation_unavailable_fallback",
            repo_id=context.repo_id,
            analysis_status=analysis.get("analysis_status"),
        )

    @staticmethod
    def _apply_validation_fallback(
        context: SearchContext,
        analysis: dict,
        reason: str,
    ) -> None:
        """
        Deterministic fallback when the validation mechanism itself fails.

        No validation success is claimed and no unsupported code
        analysis is generated.
        """

        context.validated = False
        context.validation_status = "unavailable"
        context.validation_errors = [reason]
        context.validation_retries = getattr(
            context,
            "validation_retries",
            0,
        )

        logger.warning(
            "validation_fallback_applied",
            repo_id=context.repo_id,
            reason=reason,
            analysis_available=analysis.get("analysis_available"),
        )
