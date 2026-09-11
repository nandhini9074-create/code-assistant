"""
app/modules/code_analysis/validators/code_existence_validator.py
Validates that code elements, symbols, and functions referenced in the analysis
exist in the retrieved evidence.
"""

from __future__ import annotations

from typing import Any

from app.modules.code_analysis.domain.analysis_domain import ValidationResult
from app.modules.search.domain.search_domain import RetrievedChunk


class CodeExistenceValidator:
    """Validates that referenced code elements are grounded in retrieved evidence."""

    def validate(self, analysis: dict[str, Any], chunks: list[RetrievedChunk]) -> ValidationResult:
        """
        Check if specific code symbols or lines mentioned in the analysis exist in chunks.
        """
        if not analysis:
            return ValidationResult(is_valid=False, status="failed", errors=["Analysis output is empty"])

        if not chunks:
            return ValidationResult(is_valid=True, status="passed", errors=[])

        all_chunk_text = "\n".join(c.content for c in chunks if c.content).lower()
        errors: list[str] = []

        # Check problematic_code (for FIX_BUG)
        problematic = analysis.get("problematic_code")
        if problematic and isinstance(problematic, str) and len(problematic.strip()) > 2:
            prob_lower = problematic.strip().lower()
            # If problematic_code is a symbol/short expression, check for presence
            if prob_lower not in all_chunk_text:
                # Check identifier tokens
                tokens = [t for t in prob_lower.replace("(", " ").replace(")", " ").replace(".", " ").split() if len(t) > 3]
                if tokens and not any(t in all_chunk_text for t in tokens):
                    errors.append(f"Problematic code '{problematic[:60]}' not found in retrieved chunks")

        # Check expensive_ops / bottleneck (for OPTIMIZE)
        expensive = analysis.get("expensive_ops")
        if expensive and isinstance(expensive, str) and len(expensive.strip()) > 2:
            exp_lower = expensive.strip().lower()
            if exp_lower not in all_chunk_text:
                tokens = [t for t in exp_lower.replace("(", " ").replace(")", " ").replace(".", " ").split() if len(t) > 3]
                if tokens and not any(t in all_chunk_text for t in tokens):
                    errors.append(f"Referenced operation '{expensive[:60]}' not found in retrieved chunks")

        is_valid = len(errors) == 0
        return ValidationResult(
            is_valid=is_valid,
            status="passed" if is_valid else "failed",
            errors=errors,
        )
