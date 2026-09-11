"""
app/modules/search/pipeline/evidence_validation.py
Pipeline stage: Validation (Step 10).

Executes multi-layer validation (Evidence, Code Existence, Suggestion consistency)
on the Step 9 analysis result. If invalid, executes up to 2 retries with validation feedback.
If still invalid after 2 retries, triggers Early Exit D.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.modules.code_analysis.service.code_analysis_service import CodeAnalysisService
from app.modules.search.domain.search_domain import SearchContext

logger = get_logger(__name__)

MAX_VALIDATION_RETRIES = 2


class EvidenceValidationStage:
    def __init__(self, code_analysis_service: CodeAnalysisService) -> None:
        self.code_analysis_service = code_analysis_service

    async def execute(self, context: SearchContext) -> None:
        """
        Validate Step 9 code analysis against retrieved evidence chunks.
        Performs up to MAX_VALIDATION_RETRIES re-analysis attempts if validation fails.
        Triggers Early Exit D if validation fails after all retry attempts.
        """
        if context.early_exit:
            return

        retry_count = 0

        while True:
            val_result = self.code_analysis_service.validate_analysis(
                context.analysis_result or {},
                context.retrieved_chunks,
            )

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
                # Re-run Step 9 with validation error feedback passed to analyzer
                await self.code_analysis_service.analyze(context)
            else:
                # Exhausted maximum retries -> Trigger Early Exit D
                context.validated = False
                context.validation_status = "failed"
                context.validation_errors = val_result.errors
                context.early_exit = "EARLY_EXIT_D"
                context.early_exit_message = (
                    f"Code analysis failed validation after {MAX_VALIDATION_RETRIES} retries: "
                    + "; ".join(val_result.errors)
                )
                logger.warning(
                    "early_exit_d_triggered",
                    repo_id=context.repo_id,
                    errors=val_result.errors,
                )
                return
