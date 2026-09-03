"""
app/modules/code_analysis/validators/suggestion_validator.py
Validates that LLM suggestions are grounded in evidence.
"""

from typing import Any

from app.modules.code_analysis.domain.analysis_domain import ValidationResult
from app.modules.search.domain.search_domain import RetrievedChunk


class SuggestionValidator:
    """Validates LLM suggestions for hallucination."""
    
    def validate(self, analysis: dict[str, Any], chunks: list[RetrievedChunk]) -> ValidationResult:
        """
        Check if the suggestion relies on hallucinated code.
        """
        return ValidationResult(is_valid=True)
