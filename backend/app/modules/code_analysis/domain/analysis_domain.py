"""
app/modules/code_analysis/domain/analysis_domain.py
Domain models for code analysis.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationResult:
    """Result of validating an LLM response against evidence."""
    is_valid: bool
    status: str = "passed"
    errors: list[str] = field(default_factory=list)


@dataclass
class AnalysisResult:
    """Structured result from an intent-specific analyzer."""
    intent: str
    analysis: dict[str, Any]
    validation_result: ValidationResult
