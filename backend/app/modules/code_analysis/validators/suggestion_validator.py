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

    def validate(
        self,
        analysis: dict[str, Any],
        chunks: list[RetrievedChunk],
    ) -> ValidationResult:
        """
        Check that suggestions and action plans are present, non-empty,
        and structured.
        """
        if not analysis:
            return ValidationResult(
                is_valid=False,
                status="failed",
                errors=["Analysis output is empty"],
            )

        errors: list[str] = []

        # 1. ADD_FEATURE validation
        if "required_changes" in analysis:
            changes = analysis.get("required_changes")

            if not isinstance(changes, list):
                errors.append(
                    "ADD_FEATURE analysis required_changes must be a list"
                )
            elif any(
                not isinstance(change, str) or not change.strip()
                for change in changes
            ):
                errors.append(
                    "ADD_FEATURE analysis contains empty or invalid change items"
                )

            # Validate proposed_change structure
            proposed_change = analysis.get("proposed_change")

            if not isinstance(proposed_change, dict):
                errors.append(
                    "ADD_FEATURE analysis missing proposed_change object"
                )
            else:
                description = proposed_change.get("description")
                implementation_steps = proposed_change.get(
                    "implementation_steps"
                )

                if (
                    not isinstance(description, str)
                    or not description.strip()
                ):
                    errors.append(
                        "ADD_FEATURE analysis missing proposed_change description"
                    )

                if (
                    not isinstance(implementation_steps, list)
                    or not implementation_steps
                    or any(
                        not isinstance(step, str) or not step.strip()
                        for step in implementation_steps
                    )
                ):
                    errors.append(
                        "ADD_FEATURE analysis missing implementation_steps"
                    )

        # 2. FIX_BUG proposed_fix
        if "proposed_fix" in analysis:
            fix = analysis.get("proposed_fix")
            if not fix or not isinstance(fix, str) or not fix.strip():
                errors.append("FIX_BUG analysis missing proposed_fix")

        # 3. OPTIMIZE proposed_optimization
        if "proposed_optimization" in analysis:
            opt = analysis.get("proposed_optimization")
            if not opt or not isinstance(opt, str) or not opt.strip():
                errors.append(
                    "OPTIMIZE analysis missing proposed_optimization"
                )

        # 4. REFACTOR safe_refactoring_plan
        if "safe_refactoring_plan" in analysis:
            plan = analysis.get("safe_refactoring_plan")
            if not plan or not isinstance(plan, str) or not plan.strip():
                errors.append(
                    "REFACTOR analysis missing safe_refactoring_plan"
                )

        is_valid = len(errors) == 0

        return ValidationResult(
            is_valid=is_valid,
            status="passed" if is_valid else "failed",
            errors=errors,
        )