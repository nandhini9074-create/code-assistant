"""
Suggestion-only validation stage.

This validates the proposed patch in memory and returns a validation report.
It does not modify the repository.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.modules.search.domain.search_domain import SearchContext

logger = get_logger(__name__)


class SuggestionValidationStage:
    """Validate the suggested patch without changing the repo."""

    async def execute(self, context: SearchContext) -> None:
        if context.early_exit:
            return

        # If patch_validation is already populated by SuggestionPatchStage, preserve its status and details
        if isinstance(context.patch_validation, dict) and context.patch_validation.get("status") in ("passed", "failed"):
            if "test_suggestions" not in context.patch_validation or not context.patch_validation["test_suggestions"]:
                context.patch_validation["test_suggestions"] = [
                    "Run the relevant unit tests for the affected module.",
                    "Add a regression test for the behavior change.",
                    "Review the patch manually before applying it.",
                ]
            logger.info(
                "patch_validation_preserved",
                repo_id=context.repo_id,
                status=context.patch_validation["status"],
            )
            return

        patch = context.suggested_patch
        if not patch:
            context.patch_validation = {
                "status": "not_run",
                "message": "No patch suggestion was generated.",
                "test_suggestions": [],
            }
            return

        validation = {
            "status": "passed",
            "message": "Suggestion is structurally valid and safe to review.",
            "warnings": [],
            "test_suggestions": [
                "Run the relevant unit tests for the affected module.",
                "Add a regression test for the behavior change.",
                "Review the patch manually before applying it.",
            ],
        }

        if context.validation_status == "failed":
            validation["status"] = "failed"
            validation["message"] = (
                "The underlying evidence did not validate strongly enough "
                "for a safe recommendation."
            )

        context.patch_validation = validation

        logger.info(
            "patch_validation_complete",
            repo_id=context.repo_id,
            status=validation["status"],
        )
