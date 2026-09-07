"""
app/modules/code_analysis/validators/evidence_validator.py
Validates that referenced files and paths exist in retrieved evidence chunks.
"""

from __future__ import annotations

from typing import Any

from app.modules.code_analysis.domain.analysis_domain import ValidationResult
from app.modules.search.domain.search_domain import RetrievedChunk


class EvidenceValidator:
    """Validates LLM references against provided evidence chunks."""

    def validate(self, analysis: dict[str, Any], chunks: list[RetrievedChunk]) -> ValidationResult:
        """
        Check if any referenced files/paths exist in the evidence chunks.
        """
        if not analysis:
            return ValidationResult(is_valid=False, status="failed", errors=["Analysis output is empty"])

        if "error" in analysis:
            return ValidationResult(is_valid=False, status="failed", errors=[f"Analysis error: {analysis['error']}"])

        chunk_files = {c.file_path.strip().lower() for c in chunks if c.file_path}
        chunk_basenames = {c.file_path.replace("\\", "/").split("/")[-1].strip().lower() for c in chunks if c.file_path}

        errors: list[str] = []

        # Check affected_files list
        affected_files = analysis.get("affected_files", [])
        if isinstance(affected_files, list) and chunks:
            for file_ref in affected_files:
                if not file_ref or not isinstance(file_ref, str):
                    continue
                clean_ref = file_ref.strip().lower()
                clean_base = clean_ref.replace("\\", "/").split("/")[-1]
                if clean_ref not in chunk_files and clean_base not in chunk_basenames:
                    errors.append(f"Referenced file '{file_ref}' does not exist in retrieved evidence")

        # Check single file_path if present
        file_path = analysis.get("file_path")
        if file_path and isinstance(file_path, str) and chunks:
            clean_fp = file_path.strip().lower()
            clean_base = clean_fp.replace("\\", "/").split("/")[-1]
            if clean_fp not in chunk_files and clean_base not in chunk_basenames:
                errors.append(f"Referenced file '{file_path}' does not exist in retrieved evidence")

        is_valid = len(errors) == 0
        return ValidationResult(
            is_valid=is_valid,
            status="passed" if is_valid else "failed",
            errors=errors,
        )
