"""
evaluation/exceptions.py
Custom exceptions for the evaluation framework.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from evaluation.schemas import ValidationResult


class EvaluationError(Exception):
    """Base exception for all evaluation-related errors."""


class DatasetLoadError(EvaluationError):
    """Raised when an evaluation dataset file cannot be read, parsed, or deserialized."""

    def __init__(self, message: str, file_path: str | None = None, cause: Exception | None = None) -> None:
        self.file_path = file_path
        self.cause = cause
        super().__init__(message)


class DatasetValidationError(EvaluationError):
    """Raised when an evaluation dataset fails validation."""

    def __init__(self, message: str, validation_result: ValidationResult | None = None) -> None:
        self.validation_result = validation_result
        super().__init__(message)


class AdapterError(EvaluationError):
    """Raised when an evaluation adapter fails to interact with underlying production components."""

    def __init__(self, message: str, adapter_name: str | None = None, details: dict[str, Any] | None = None) -> None:
        self.adapter_name = adapter_name
        self.details = details or {}
        super().__init__(message)
