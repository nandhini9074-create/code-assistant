"""
app/modules/code_analysis/validators/suggestion_validator.py
Validates that LLM suggestions, proposed fixes, or changes are well-formed,
actionable, and consistent.
"""

from __future__ import annotations

from typing import Any

from app.modules.code_analysis.domain.analysis_domain import ValidationResult
from app.modules.search.domain.search_domain import RetrievedChunk


class SuggestionValidator:
    """Validates that proposed changes/suggestions are non-empty and well-formed."""

    def validate(self, analysis: dict[str, Any], chunks: list[RetrievedChunk]) -> ValidationResult:
        """
        Check that suggestions and action plans are present, non-empty, and structured.
        """
        if not analysis:
            return ValidationResult(is_valid=False, status="failed", errors=["Analysis output is empty"])

        errors: list[str] = []

        # 1. ADD_FEATURE required_changes
        if "required_changes" in analysis:
            changes = analysis.get("required_changes")
            if not isinstance(changes, list) or len(changes) == 0:
                errors.append("ADD_FEATURE analysis missing required_changes list")
            elif any(not str(c).strip() for c in changes):
                errors.append("ADD_FEATURE analysis contains empty change items")

        # 2. FIX_BUG proposed_fix
        if "proposed_fix" in analysis:
            fix = analysis.get("proposed_fix")
            if not fix or not isinstance(fix, str) or not fix.strip():
                errors.append("FIX_BUG analysis missing proposed_fix")

        # 3. OPTIMIZE proposed_optimization
        if "proposed_optimization" in analysis:
            opt = analysis.get("proposed_optimization")
            if not opt or not isinstance(opt, str) or not opt.strip():
                errors.append("OPTIMIZE analysis missing proposed_optimization")

        # 4. REFACTOR safe_refactoring_plan
        if "safe_refactoring_plan" in analysis:
            plan = analysis.get("safe_refactoring_plan")
            if not plan or not isinstance(plan, str) or not plan.strip():
                errors.append("REFACTOR analysis missing safe_refactoring_plan")

        is_valid = len(errors) == 0
        return ValidationResult(
            is_valid=is_valid,
            status="passed" if is_valid else "failed",
            errors=errors,
        )
