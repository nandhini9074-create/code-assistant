
"""
app/modules/search/pipeline/action_analysis.py

Pipeline stage: Change / Action Analysis (Step 11).

Converts validated code analysis into a structured description
of the proposed action.

This stage is advisory only and does not modify repository files.

For code-change intents, this stage may carry an exact code_change
specification containing:
    file_path
    old_code
    new_code

The actual patch is generated later by SuggestionPatchStage.
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

        # No analysis available.
        if not context.analysis_result:
            context.action_analysis = None

            logger.warning(
                "action_analysis_unavailable",
                repo_id=context.repo_id,
                reason="No code analysis result available.",
            )
            return

        # ---------------------------------------------------------
        # Fallback when Step 10 validation is unavailable.
        # ---------------------------------------------------------
        if context.validation_status == "unavailable":
            context.action_analysis = {
                "action_status": "UNAVAILABLE",
                "action_available": False,
                "action_type": None,
                "proposed_change": None,
                "code_change": None,
                "affected_target": _build_affected_target(context),
                "rationale": None,
                "risk_level": "unknown",
                "is_applied": False,
            }

            logger.warning(
                "action_analysis_validation_unavailable",
                repo_id=context.repo_id,
            )
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

        # ---------------------------------------------------------
        # Extract exact source-code change.
        #
        # Expected:
        #
        # "code_change": {
        #     "file_path": "...",
        #     "old_code": "...",
        #     "new_code": "..."
        # }
        #
        # No patch is generated here.
        # ---------------------------------------------------------
        code_change = _extract_code_change(
            analysis,
            context,
        )

        context.action_analysis = {
            "action_type": action_type,
            "proposed_change": proposed_change,
            "code_change": code_change,
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
            has_code_change=code_change is not None,
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


def _extract_code_change(
    analysis: dict[str, Any],
    context: SearchContext,
) -> dict[str, str] | None:
    """
    Extract an exact code-change specification from validated analysis.

    Expected structure:

        {
            "file_path": "app/example.py",
            "old_code": "old source code",
            "new_code": "new source code"
        }

    This function deliberately does not construct old_code/new_code
    from proposed_change or suggested_code.

    The LLM must explicitly provide the source-code content.
    """

    value = analysis.get("code_change")

    if not isinstance(value, dict):
        return None

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
        logger.warning(
            "invalid_code_change_structure",
            repo_id=context.repo_id,
        )
        return None

    file_path = file_path.strip()

    # Do not allow the LLM to redirect the change to another file.
    target = _build_affected_target(context)
    target_file_path = target.get("file_path")

    if (
        isinstance(target_file_path, str)
        and target_file_path not in {"", "unknown"}
        and file_path != target_file_path
    ):
        logger.warning(
            "code_change_file_mismatch",
            repo_id=context.repo_id,
            expected_file=target_file_path,
            provided_file=file_path,
        )
        return None

    # Do not accept a no-op change.
    if old_code == new_code:
        logger.warning(
            "code_change_noop",
            repo_id=context.repo_id,
            file_path=file_path,
        )
        return None

    return {
        "file_path": file_path,
        "old_code": old_code,
        "new_code": new_code,
    }


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

    repository = context.repo_name or context.repo_id

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

