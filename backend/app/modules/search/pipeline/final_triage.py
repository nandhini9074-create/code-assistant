
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
        #
        # A change is considered safe to recommend for application
        # only when:
        #
        # 1. Validation passed.
        # 2. Confidence is HIGH or MEDIUM.
        #
        # This does NOT mean the system has automatically applied
        # the change.
        #
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

    if context.intent:
        intent_label = context.intent.value.replace(
            "_",
            " ",
        ).title()
    else:
        intent_label = "Query"

    target_name = context.target_symbol

    if not target_name and context.primary_chunk:
        target_name = context.primary_chunk.file_path

    if not target_name:
        target_name = "codebase"

    return (
        f"{intent_label} request regarding "
        f"`{target_name}`: {context.query}"
    )


def _build_ai_suggestion(
    context: SearchContext,
    analysis: dict[str, Any],
    action: dict[str, Any],
) -> str:
    """
    Build a grounded suggestion from the validated analysis.

    Only fields actually present in the analysis/action result
    are included.
    """

    parts: list[str] = []

    if analysis.get("existing_implementation"):
        parts.append(
            f"Current state: "
            f"{analysis['existing_implementation']}"
        )

    if analysis.get("current_behavior"):
        parts.append(
            f"Observed behavior: "
            f"{analysis['current_behavior']}"
        )

    if analysis.get("likely_cause"):
        parts.append(
            f"Root cause: "
            f"{analysis['likely_cause']}"
        )

    if analysis.get("bottleneck"):
        parts.append(
            f"Bottleneck: "
            f"{analysis['bottleneck']}"
        )

    if analysis.get("code_smell"):
        parts.append(
            f"Identified smell: "
            f"{analysis['code_smell']}"
        )

    change_desc = action.get("proposed_change")

    if change_desc:
        parts.append(
            f"Recommended action: {change_desc}"
        )

    rationale = action.get("rationale")

    if rationale:
        parts.append(
            f"Rationale: {rationale}"
        )

    if not parts:
        return (
            "No additional validated analysis was available. "
            f"Original request: {context.query}"
        )

    return " | ".join(parts)


def _compute_confidence(
    context: SearchContext,
    validation_status: str,
) -> str:
    """
    Determine confidence from evidence quality and validation.

    Confidence levels:
    - NONE: no usable retrieval evidence.
    - LOW: weak evidence or failed validation.
    - MEDIUM: reasonable retrieval evidence.
    - HIGH: strong evidence plus an identified primary chunk.
    """

    if validation_status == "failed":
        return ConfidenceLevel.LOW.value

    if context.early_exit == "EARLY_EXIT_D":
        return ConfidenceLevel.LOW.value

    if not context.retrieved_chunks:
        return ConfidenceLevel.NONE.value

    # Explicitly sort rather than assuming HybridSearch already
    # returned chunks in score order.
    ranked_chunks = sorted(
        context.retrieved_chunks,
        key=lambda chunk: chunk.score,
        reverse=True,
    )

    top_scores = [
        chunk.score
        for chunk in ranked_chunks[:3]
    ]

    if not top_scores:
        return ConfidenceLevel.NONE.value

    avg_score = sum(top_scores) / len(top_scores)

    if (
        avg_score >= 0.75
        and context.primary_chunk is not None
    ):
        return ConfidenceLevel.HIGH.value

    if avg_score >= 0.45:
        return ConfidenceLevel.MEDIUM.value

    return ConfidenceLevel.LOW.value


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
