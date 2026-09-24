
"""
app/modules/search/pipeline/change_planning.py

Pipeline stage: Change Planning (Step 11).

Converts validated action analysis into a structured, non-mutating
implementation plan for the requested change.

This stage does NOT modify repository files.

For FIX_BUG / ADD_FEATURE / OPTIMIZE / REFACTOR requests, the plan may
also carry an exact code_change specification containing:

    file_path
    old_code
    new_code

The exact code_change is consumed later by the suggestion-only patch
generation stage to create a real unified diff.
"""

from __future__ import annotations

from typing import Any

from app.core.enums import IntentType
from app.core.logging import get_logger
from app.modules.search.domain.search_domain import SearchContext

logger = get_logger(__name__)


class ChangePlanningStage:
    """Build a conservative implementation plan from validated code analysis."""

    async def execute(self, context: SearchContext) -> None:
        """Create a safe, non-mutating change plan."""

        if context.early_exit:
            logger.info(
                "change_planning_skipped",
                reason=context.early_exit,
                repo_id=context.repo_id,
            )
            return

        if context.intent in (None, IntentType.RETRIEVE):
            context.change_plan = None
            return

        if context.validation_status in {"failed", "unavailable"}:
            context.change_plan = None
            return

        action = context.action_analysis or {}
        analysis = context.analysis_result or {}

        if not isinstance(action, dict) and not isinstance(analysis, dict):
            context.change_plan = None
            return

        summary = _extract_change_summary(
            context,
            action,
            analysis,
        )

        if not summary:
            context.change_plan = None
            return

        implementation_steps = _extract_implementation_steps(
            context,
            action,
            analysis,
        )

        code_change = _extract_code_change(
            action,
            analysis,
            context,
        )

        plan: dict[str, Any] = {
            "change_type": (
                action.get("action_type")
                if isinstance(action, dict)
                else _determine_change_type(context.intent)
            )
            or _determine_change_type(context.intent),

            "summary": summary,

            "implementation_steps": implementation_steps,

            "validation_steps": _build_validation_steps(context),

            "risk_level": (
                action.get("risk_level")
                if isinstance(action, dict)
                else "low"
            )
            or "low",

            "target": (
                action.get("affected_target")
                if isinstance(action, dict)
                else _build_target(context)
            )
            or _build_target(context),

            # Exact code change used by the suggestion-only patch stage.
            # None is intentional when the previous LLM stage did not
            # provide enough information to safely construct a real patch.
            "code_change": code_change,
        }

        context.change_plan = plan

        if context.triage_result is not None:
            context.triage_result["change_plan"] = plan

        logger.info(
            "change_planning_complete",
            repo_id=context.repo_id,
            intent=context.intent.value if context.intent else None,
            change_type=plan["change_type"],
            has_code_change=code_change is not None,
        )


def _determine_change_type(intent: IntentType | None) -> str:
    """Map intent to a safe change category."""

    mapping = {
        IntentType.ADD_FEATURE: "FEATURE_IMPLEMENTATION",
        IntentType.FIX_BUG: "BUG_REMEDIATION",
        IntentType.OPTIMIZE: "PERFORMANCE_OPTIMIZATION",
        IntentType.REFACTOR: "CODE_REFACTORING",
    }

    return mapping.get(intent, "CODE_MODIFICATION")


def _extract_change_summary(
    context: SearchContext,
    action: dict[str, Any],
    analysis: dict[str, Any],
) -> str | None:
    """Extract the safest available high-level change summary."""

    if isinstance(action, dict):
        summary = action.get("proposed_change")

        if isinstance(summary, str) and summary.strip():
            return summary.strip()

    for key in (
        "proposed_fix",
        "proposed_change",
        "recommended_change",
        "safe_refactoring_plan",
        "proposed_optimization",
        "suggestion",
    ):
        value = analysis.get(key)

        if isinstance(value, str) and value.strip():
            return value.strip()

        if isinstance(value, dict):
            description = value.get("description")

            if isinstance(description, str) and description.strip():
                return description.strip()

    return None


def _extract_implementation_steps(
    context: SearchContext,
    action: dict[str, Any],
    analysis: dict[str, Any],
) -> list[str]:
    """Collect a conservative list of implementation steps."""

    steps: list[str] = []

    if isinstance(action, dict):
        proposed = action.get("proposed_change")

        if isinstance(proposed, str) and proposed.strip():
            steps.append(proposed.strip())

    for key in (
        "proposed_change",
        "proposed_fix",
        "recommended_change",
        "safe_refactoring_plan",
        "proposed_optimization",
    ):
        value = analysis.get(key)

        if isinstance(value, dict):
            entries = value.get("implementation_steps")

            if isinstance(entries, list):
                steps.extend(
                    str(item).strip()
                    for item in entries
                    if str(item).strip()
                )

        elif isinstance(value, str) and value.strip():
            steps.append(value.strip())

    if not steps:
        summary = _extract_change_summary(
            context,
            action,
            analysis,
        )

        if summary:
            steps = [summary]

    # Remove duplicate steps while preserving order.
    unique_steps: list[str] = []

    for step in steps:
        if step not in unique_steps:
            unique_steps.append(step)

    return unique_steps[:6]


def _extract_code_change(
    action: dict[str, Any],
    analysis: dict[str, Any],
    context: SearchContext,
) -> dict[str, Any] | None:
    """
    Extract an exact code-change specification.

    Expected structure:

        {
            "file_path": "app/example.py",
            "old_code": "old source code",
            "new_code": "new source code"
        }

    This function deliberately does NOT attempt to manufacture old_code
    or new_code from a textual proposed_change. A real patch must be based
    on explicit source-code content.
    """

    sources: list[dict[str, Any]] = []

    if isinstance(action, dict):
        sources.append(action)

    if isinstance(analysis, dict):
        sources.append(analysis)

    # Also inspect nested structures that may contain the exact change.
    nested_values: list[Any] = []

    for source in sources:
        for key in (
            "code_change",
            "suggested_change",
            "change",
            "patch_change",
        ):
            value = source.get(key)

            if value is not None:
                nested_values.append(value)

    for value in nested_values:
        if not isinstance(value, dict):
            continue

        file_path = value.get("file_path")
        old_code = value.get("old_code")
        new_code = value.get("new_code")

        if not (
            isinstance(file_path, str)
            and file_path.strip()
            and isinstance(old_code, str)
            and old_code.strip()
            and isinstance(new_code, str)
            and new_code.strip()
        ):
            continue

        resolved_file_path = file_path.strip()

        # If a target file is already known, do not allow the LLM output
        # to silently redirect the proposed change to another file.
        target = _build_target(context)
        target_file_path = target.get("file_path")

        if (
            isinstance(target_file_path, str)
            and target_file_path not in {"unknown", ""}
            and resolved_file_path != target_file_path
        ):
            logger.warning(
                "code_change_file_mismatch",
                expected_file=target_file_path,
                provided_file=resolved_file_path,
                repo_id=context.repo_id,
            )
            continue

        return {
            "file_path": resolved_file_path,
            "old_code": old_code,
            "new_code": new_code,
        }

    return None


def _build_validation_steps(
    context: SearchContext,
) -> list[str]:
    """Describe validation without applying repository changes."""

    base_steps = [
        "Review the targeted code path and confirm the root cause.",
        "Run the relevant repository tests or smoke checks.",
        "Verify the change preserves current behavior outside the targeted scope.",
    ]

    if context.intent == IntentType.ADD_FEATURE:
        base_steps.insert(
            1,
            "Confirm the new behavior is exposed at the intended integration point.",
        )

    elif context.intent == IntentType.FIX_BUG:
        base_steps.insert(
            1,
            "Verify the fix addresses the observed failure scenario or bug trigger.",
        )

    elif context.intent == IntentType.OPTIMIZE:
        base_steps.insert(
            1,
            "Benchmark the optimized path and confirm the performance gain does not change semantics.",
        )

    elif context.intent == IntentType.REFACTOR:
        base_steps.insert(
            1,
            "Check that the refactor preserves existing behavior and public interfaces.",
        )

    return base_steps


def _build_target(
    context: SearchContext,
) -> dict[str, Any]:
    """Build a conservative target record from retrieved evidence."""

    if context.primary_chunk:
        file_path = context.primary_chunk.file_path
        metadata = context.primary_chunk.metadata or {}

        line_range = None

        start_line = metadata.get("start_line")
        end_line = metadata.get("end_line")

        if start_line is not None and end_line is not None:
            line_range = f"{start_line}-{end_line}"

    elif context.file_paths:
        file_path = context.file_paths[0]
        line_range = None

    else:
        file_path = "unknown"
        line_range = None

    repository = context.repo_name or context.repo_id

    if context.repo_owner and context.repo_name:
        repository = f"{context.repo_owner}/{context.repo_name}"

    return {
        "repository": repository,
        "file_path": file_path,
        "symbol": context.target_symbol or "global",
        "line_range": line_range,
    }

