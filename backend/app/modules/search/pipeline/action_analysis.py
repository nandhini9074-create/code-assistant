"""
app/modules/search/pipeline/action_analysis.py

Pipeline stage: Change / Action Analysis (Step 11).

Converts validated code analysis into a structured description
of the proposed action.

This stage is advisory only and does not modify repository files.
"""

from __future__ import annotations

from typing import Any

from app.core.enums import IntentType
from app.core.logging import get_logger
from app.modules.search.domain.search_domain import SearchContext

logger = get_logger(__name__)


class ActionAnalysisStage:
    """Build structured action information from validated analysis."""

    async def execute(self, context: SearchContext) -> None:
        """Execute Step 11 action analysis."""

        if context.early_exit:
            return

        if not context.analysis_result:
            context.action_analysis = None
            return

        if not context.validated:
            logger.warning(
                "action_analysis_skipped_unvalidated_analysis",
                repo_id=context.repo_id,
                validation_status=context.validation_status,
            )
            context.action_analysis = None
            return

        analysis = context.analysis_result
        intent = context.intent

        # RETRIEVE does not require change/action analysis.
        if intent == IntentType.RETRIEVE:
            context.action_analysis = None
            return

        action_type = _determine_action_type(intent)

        proposed_change = str(
            analysis.get("proposed_change")
            or analysis.get("proposed_fix")
            or analysis.get("proposed_optimization")
            or analysis.get("safe_refactoring_plan")
            or analysis.get("suggestion")
            or ""
        ).strip()

        affected_target = _build_affected_target(context)

        rationale = str(
            analysis.get("rationale")
            or analysis.get("likely_cause")
            or analysis.get("code_smell")
            or ""
        ).strip()

        risk_level = _assess_risk(
            analysis,
            context,
        )

        context.action_analysis = {
            "action_type": action_type,
            "proposed_change": proposed_change,
            "affected_target": affected_target,
            "rationale": rationale,
            "risk_level": risk_level,
            "is_applied": False,
        }

        logger.info(
            "action_analysis_complete",
            repo_id=context.repo_id,
            action_type=action_type,
            target_file=affected_target.get("file_path"),
            risk_level=risk_level,
        )


def _determine_action_type(
    intent: IntentType | None,
) -> str:
    """Map intent to an action category."""

    action_types = {
        IntentType.ADD_FEATURE: "FEATURE_IMPLEMENTATION",
        IntentType.FIX_BUG: "BUG_REMEDIATION",
        IntentType.OPTIMIZE: "PERFORMANCE_OPTIMIZATION",
        IntentType.REFACTOR: "CODE_REFACTORING",
    }

    return action_types.get(
        intent,
        "CODE_MODIFICATION",
    )


def _build_affected_target(
    context: SearchContext,
) -> dict[str, Any]:
    """Build the target from repository evidence."""

    file_path = None
    line_range = None

    if context.primary_chunk:
        file_path = context.primary_chunk.file_path

        metadata = context.primary_chunk.metadata or {}

        start_line = metadata.get("start_line")
        end_line = metadata.get("end_line")

        if start_line is not None and end_line is not None:
            line_range = f"{start_line}-{end_line}"

    elif context.file_paths:
        file_path = context.file_paths[0]

    elif context.retrieved_chunks:
        file_path = context.retrieved_chunks[0].file_path

    repository = context.repo_id

    if context.repo_owner and context.repo_name:
        repository = (
            f"{context.repo_owner}/{context.repo_name}"
        )

    return {
        "repository": repository,
        "file_path": file_path or "unknown",
        "symbol": context.target_symbol or "global",
        "line_range": line_range,
    }


def _assess_risk(
    analysis: dict[str, Any],
    context: SearchContext,
) -> str:
    """Provide a coarse advisory risk classification."""

    affected_files = analysis.get(
        "affected_files",
        [],
    )

    if isinstance(affected_files, list):
        file_count = len(affected_files)
    else:
        file_count = 0

    if file_count > 3:
        return "high"

    if context.validation_status == "failed":
        return "high"

    if context.intent in (
        IntentType.ADD_FEATURE,
        IntentType.REFACTOR,
    ):
        return "medium"

    return "low"