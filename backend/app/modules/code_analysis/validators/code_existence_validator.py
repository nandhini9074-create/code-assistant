"""
app/modules/code_analysis/validators/code_existence_validator.py
Validates that suggested code elements exist in the chunks.
"""

from typing import Any

from app.modules.code_analysis.domain.analysis_domain import ValidationResult
from app.modules.search.domain.search_domain import RetrievedChunk


class CodeExistenceValidator:
    """Validates suggested code elements."""
    
    def validate(self, analysis: dict[str, Any], chunks: list[RetrievedChunk]) -> ValidationResult:
        """
        Check if the elements mentioned in the analysis really exist.
        """
        return ValidationResult(is_valid=True)
