
"""
app/modules/search/pipeline/action_analysis.py

Pipeline stage: Change / Action Analysis (Step 11).

Transforms validated Step 9 analysis into a structured description of
the proposed action. This stage is advisory only and does not modify
repository files or claim that any change has been applied.
"""

from __future__ import annotations

from typing import Any

from app.core.enums import IntentType
from app.core.logging import get_logger
from app.modules.search.domain.search_domain import SearchContext

logger = get_logger(__name__)


class ActionAnalysisStage:
    """
    Construct actionable change analysis from validated code analysis.

    This stage does not modify source code.
    """

    async def execute(self, context: SearchContext) -> None:
        """Execute Step 11 action analysis."""

        if context.early_exit:
            return

        if not context.analysis_result:
            logger.warning(
                "action_analysis_skipped_no_analysis",
                repo_id=context.repo_id,
            )
            context.action_analysis = None
            return

        # Step 11 should consume validated Step 9 output.
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

        action_type = _determine_action_type(intent)
        proposed_change = _extract_proposed_change(
            analysis,
            intent,
        )
        affected_target = _build_affected_target(
            context,
            analysis,
        )
        change_representation = _generate_change_representation(
            context,
            analysis,
            proposed_change,
        )
        rationale = _extract_rationale(
            analysis,
            intent,
        )
        risk_level = _assess_risk(
            analysis,
            context,
        )

        action_result: dict[str, Any] = {
            "action_type": action_type,
            "proposed_change": proposed_change,
            "affected_target": affected_target,
            "diff_or_change": change_representation,
            "rationale": rationale,
            "risk_level": risk_level,
            "is_applied": False,
        }

        context.action_analysis = action_result

        logger.info(
            "action_analysis_complete",
            action_type=action_type,
            target_file=affected_target.get("file_path"),
            risk_level=risk_level,
        )


def _determine_action_type(
    intent: IntentType | None,
) -> str:
    """Map the classified intent to an action category."""

    action_types = {
        IntentType.ADD_FEATURE: "FEATURE_IMPLEMENTATION",
        IntentType.FIX_BUG: "BUG_REMEDIATION",
        IntentType.OPTIMIZE: "PERFORMANCE_OPTIMIZATION",
        IntentType.REFACTOR: "CODE_REFACTORING",
        IntentType.RETRIEVE: "CODE_RETRIEVAL",
    }

    return action_types.get(
        intent,
        "CODE_MODIFICATION",
    )


def _extract_proposed_change(
    analysis: dict[str, Any],
    intent: IntentType | None,
) -> str:
    """Extract the proposed modification from intent-specific analysis.

    Prefers the top-level ``proposed_change`` key (actual code produced by
    the LLM) over older intent-specific fields so the suggestion always
    contains concrete code rather than a natural-language description.
    """

    # Primary preference: actual code returned by any analyzer.
    if analysis.get("proposed_change"):
        return str(analysis["proposed_change"]).strip()

    # Intent-specific fallbacks (natural-language fields retained for
    # backward compatibility).
    if intent == IntentType.ADD_FEATURE:
        changes = analysis.get("required_changes")

        if isinstance(changes, list) and changes:
            return "; ".join(
                str(change)
                for change in changes
            )

        return str(
            analysis.get(
                "existing_implementation",
                "Implement the requested feature based on the available evidence.",
            )
        )

    if intent == IntentType.FIX_BUG:
        return str(
            analysis.get("proposed_fix")
            or analysis.get("likely_cause")
            or "Apply the proposed bug remediation."
        )

    if intent == IntentType.OPTIMIZE:
        return str(
            analysis.get("proposed_optimization")
            or analysis.get("bottleneck")
            or "Apply the proposed performance optimization."
        )

    if intent == IntentType.REFACTOR:
        return str(
            analysis.get("safe_refactoring_plan")
            or analysis.get("code_smell")
            or "Apply the proposed refactoring."
        )

    if intent == IntentType.RETRIEVE:
        return str(
            analysis.get("answer")
            or analysis.get("proposed_change")
            or analysis.get("suggestion")
            or analysis.get("current_behavior")
            or "Retrieved repository code."
        ).strip()

    return "Modify the identified code based on the available evidence."



def _build_affected_target(
    context: SearchContext,
    analysis: dict[str, Any],
) -> dict[str, Any]:
    """
    Determine the primary repository target.

    Prefer retrieved repository evidence over LLM-generated file names.
    """

    file_path: str | None = None

    # Strongest source: primary retrieved chunk.
    if context.primary_chunk and context.primary_chunk.file_path:
        file_path = context.primary_chunk.file_path

    # Next: explicitly retrieved/query-derived file path.
    elif context.file_paths:
        file_path = context.file_paths[0]

    # Last repository-evidence fallback.
    elif context.retrieved_chunks:
        file_path = context.retrieved_chunks[0].file_path

    line_range: str | None = None

    if context.primary_chunk:
        metadata = context.primary_chunk.metadata or {}

        start_line = metadata.get("start_line")
        end_line = metadata.get("end_line")

        if start_line is not None and end_line is not None:
            line_range = f"{start_line}-{end_line}"

    repository = context.repo_id

    if context.repo_owner and context.repo_name:
        repository = f"{context.repo_owner}/{context.repo_name}"

    return {
        "repository": repository,
        "file_path": file_path or "unknown",
        "symbol": context.target_symbol or "global",
        "line_range": line_range,
    }


def _generate_change_representation(
    context: SearchContext,
    analysis: dict[str, Any],
    proposed_change: str,
) -> str:
    """
    Generate an advisory change representation.

    This is NOT an executable patch and must not imply that repository
    files have been modified.
    """

    target_file = "unknown"

    if context.primary_chunk:
        target_file = context.primary_chunk.file_path
    elif context.file_paths:
        target_file = context.file_paths[0]
    elif context.retrieved_chunks:
        target_file = context.retrieved_chunks[0].file_path

    symbol = context.target_symbol or "target_element"

    lines = [
        f"Target: {target_file}",
        f"Symbol: {symbol}",
        "Change representation: advisory only",
    ]

    if context.intent == IntentType.FIX_BUG:
        problematic_code = analysis.get("problematic_code")
        proposed_fix = analysis.get("proposed_fix")

        if problematic_code:
            lines.append("Current/problematic code:")
            lines.extend(
                f"- {line}"
                for line in str(problematic_code).splitlines()
            )

        if proposed_fix:
            lines.append("Proposed change:")
            lines.extend(
                f"+ {line}"
                for line in str(proposed_fix).splitlines()
            )
        else:
            lines.append(
                f"Proposed fix: {proposed_change}"
            )

    elif context.intent == IntentType.ADD_FEATURE:
        lines.append(
            f"Proposed feature change: {proposed_change}"
        )

        required_changes = analysis.get(
            "required_changes",
            [],
        )

        if isinstance(required_changes, list):
            for change in required_changes[:5]:
                lines.append(
                    f"- {change}"
                )

    elif context.intent == IntentType.OPTIMIZE:
        bottleneck = analysis.get(
            "bottleneck",
            "No specific bottleneck identified.",
        )

        optimization = analysis.get(
            "proposed_optimization",
            proposed_change,
        )

        lines.append(
            f"Identified bottleneck: {bottleneck}"
        )
        lines.append(
            f"Proposed optimization: {optimization}"
        )

    elif context.intent == IntentType.REFACTOR:
        code_smell = analysis.get(
            "code_smell",
            "No specific code smell identified.",
        )

        refactoring_plan = analysis.get(
            "safe_refactoring_plan",
            proposed_change,
        )

        lines.append(
            f"Identified code smell: {code_smell}"
        )
        lines.append(
            f"Proposed refactoring: {refactoring_plan}"
        )

    else:
        lines.append(
            f"Proposed change: {proposed_change}"
        )

    lines.append(
        "NOTE: No repository changes were applied."
    )

    return "\n".join(lines)


def _extract_rationale(
    analysis: dict[str, Any],
    intent: IntentType | None,
) -> str:
    """Extract the reasoning supporting the proposed action."""

    if intent == IntentType.ADD_FEATURE:
        return str(
            analysis.get(
                "rationale"
            )
            or analysis.get(
                "risks"
            )
            or "Extends repository functionality based on the analyzed requirements."
        )

    if intent == IntentType.FIX_BUG:
        return str(
            analysis.get(
                "likely_cause"
            )
            or analysis.get(
                "rationale"
            )
            or "Addresses the identified defect based on the available repository evidence."
        )

    if intent == IntentType.OPTIMIZE:
        return str(
            analysis.get(
                "rationale"
            )
            or analysis.get(
                "expensive_ops"
            )
            or "Reduces unnecessary execution or resource overhead."
        )

    if intent == IntentType.REFACTOR:
        return str(
            analysis.get(
                "rationale"
            )
            or analysis.get(
                "duplication"
            )
            or "Improves maintainability, readability, and modularity."
        )

    return (
        "Proposed action is based on the available repository analysis."
    )


def _assess_risk(
    analysis: dict[str, Any],
    context: SearchContext,
) -> str:
    """
    Estimate modification risk from the analyzed scope.

    This is a coarse advisory classification, not a guarantee of safety.
    """

    affected_files = analysis.get(
        "affected_files",
        [],
    )

    if isinstance(affected_files, list):
        affected_file_count = len(affected_files)
    else:
        affected_file_count = 0

    if affected_file_count > 3:
        return "high"

    if context.validation_status == "failed":
        return "high"

    if context.early_exit:
        return "high"

    if context.intent in (
        IntentType.ADD_FEATURE,
        IntentType.REFACTOR,
    ):
        return "medium"

    return "low"
