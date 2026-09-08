
"""
app/modules/search/pipeline/final_triage.py

Pipeline stage: Final AI Triage Engine (Step 12).

Synthesizes:
- retrieved repository evidence
- validated intent-specific analysis
- action analysis
- validation status

into a final triage assessment with confidence and safety checks.

This stage does not modify repository files.
"""

from __future__ import annotations

from typing import Any

from app.core.enums import ConfidenceLevel
from app.core.logging import get_logger
from app.modules.search.domain.search_domain import SearchContext

logger = get_logger(__name__)


class FinalTriageStage:
    """Performs final AI triage and risk-checked synthesis."""

    async def execute(self, context: SearchContext) -> None:
        """
        Execute final triage and populate context.triage_result.

        Triage is only meaningful when the pipeline has not already
        exited. Failed validation is explicitly reflected in the
        resulting safety and confidence fields.
        """

        if context.early_exit:
            logger.info(
                "final_triage_skipped",
                reason=context.early_exit,
                repo_id=context.repo_id,
            )
            return

        analysis = context.analysis_result or {}
        action = context.action_analysis or {}

        validation_status = context.validation_status

        if validation_status is None:
            validation_status = (
                "passed" if context.validated else "failed"
            )

        # ---------------------------------------------------------
        # Build triage components
        # ---------------------------------------------------------

        issue_summary = _build_issue_summary(
            context,
            analysis,
        )

        recommended_change = (
            action.get("proposed_change")
            if isinstance(action, dict)
            else None
        )

        if not recommended_change:
            recommended_change = (
                "Review the validated analysis before applying any change."
            )

        # Keep the public suggestion concise.
        ai_suggestion = _build_ai_suggestion(
            context,
            analysis,
            action,
        )

        confidence = _compute_confidence(
            context,
            validation_status,
        )

        target = (
            action.get("affected_target")
            if isinstance(action, dict)
            else None
        ) or {}

        proposed_diff = (
            action.get("diff_or_change")
            if isinstance(action, dict)
            else None
        )

        risk_level = (
            action.get("risk_level", "low")
            if isinstance(action, dict)
            else "low"
        )

        # ---------------------------------------------------------
        # Safety determination
        # ---------------------------------------------------------

        is_safe = (
            validation_status == "passed"
            and confidence
            in (
                ConfidenceLevel.HIGH.value,
                ConfidenceLevel.MEDIUM.value,
            )
        )

        warning = _build_warning(
            context,
            validation_status,
            confidence,
        )

        triage_output: dict[str, Any] = {
            "issue_summary": issue_summary,
            "recommended_change": recommended_change,
            "ai_suggestion": ai_suggestion,
            "confidence": confidence,
            "target": target,
            "proposed_diff": proposed_diff,
            "validation_status": validation_status,
            "is_safe_to_apply": is_safe,
            "warning": warning,
            "risk_level": risk_level,
        }

        context.triage_result = triage_output

        logger.info(
            "final_triage_complete",
            repo_id=context.repo_id,
            confidence=confidence,
            validation_status=validation_status,
            risk_level=risk_level,
            is_safe=is_safe,
        )


def _build_issue_summary(
    context: SearchContext,
    analysis: dict[str, Any],
) -> str:
    """Build a concise summary of the user's request and target."""

    return context.query.strip()


def _build_ai_suggestion(
    context: SearchContext,
    analysis: dict[str, Any],
    action: dict[str, Any],
) -> str:
    """
    Build a concise, grounded suggestion for the final API response.

    Detailed reasoning remains internally available through
    analysis_result and action_analysis.

    The public suggestion contains only the recommended action.
    """

    # ---------------------------------------------------------
    # Preferred source: action analysis
    # ---------------------------------------------------------

    change_desc = (
        action.get("proposed_change")
        if isinstance(action, dict)
        else None
    )

    if change_desc:
        return str(change_desc).strip()

    # ---------------------------------------------------------
    # Fallback: validated analysis
    # ---------------------------------------------------------

    if analysis.get("recommended_change"):
        return str(
            analysis["recommended_change"]
        ).strip()

    if analysis.get("suggestion"):
        return str(
            analysis["suggestion"]
        ).strip()

    # ---------------------------------------------------------
    # Final fallback: current behavior
    # ---------------------------------------------------------

    if analysis.get("current_behavior"):
        target_name = context.target_symbol or "target"

        return (
            f"The `{target_name}` currently "
            f"{analysis['current_behavior']}"
        )

    return "No additional validated recommendation is available."


def _compute_confidence(
    context: SearchContext,
    validation_status: str,
) -> str:
    """
    Determine confidence from evidence quality and validation.

    Retrieval scores can vary depending on the embedding model,
    vector database, reranker, and scoring strategy. Therefore,
    fixed thresholds such as 0.75 and 0.45 should not be assumed
    to be universal.

    Confidence levels:
    - NONE: no usable retrieval evidence.
    - LOW: weak evidence or failed validation.
    - MEDIUM: usable evidence without full validation.
    - HIGH: retrieved evidence + primary target + passed validation.
    """

    if validation_status == "failed":
        return ConfidenceLevel.LOW.value

    if context.early_exit == "EARLY_EXIT_D":
        return ConfidenceLevel.LOW.value

    if not context.retrieved_chunks:
        return ConfidenceLevel.NONE.value

    if context.primary_chunk is None:
        return ConfidenceLevel.LOW.value

    if validation_status == "passed":
        return ConfidenceLevel.HIGH.value

    return ConfidenceLevel.MEDIUM.value


def _build_warning(
    context: SearchContext,
    validation_status: str,
    confidence: str,
) -> str | None:
    """Build a safety warning when triage confidence is insufficient."""

    if validation_status == "failed":
        return (
            "Validation failed: the proposed analysis could not be "
            "sufficiently grounded in retrieved repository evidence. "
            "Manual verification is required."
        )

    if confidence == ConfidenceLevel.NONE.value:
        return (
            "No usable repository evidence was available. "
            "The result should not be used to make code changes."
        )

    if confidence == ConfidenceLevel.LOW.value:
        return (
            "Low confidence: repository evidence was insufficient "
            "for a reliable recommendation. Manual verification "
            "is strongly advised."
        )

    if context.primary_chunk is None:
        return (
            "No primary code target was identified. "
            "Verify the affected code before applying changes."
        )

    return None
