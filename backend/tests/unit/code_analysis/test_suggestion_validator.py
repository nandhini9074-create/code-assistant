"""Unit tests for SuggestionValidator."""

from app.modules.code_analysis.domain.analysis_domain import ValidationResult
from app.modules.code_analysis.validators.suggestion_validator import (
    SuggestionValidator,
)
from app.modules.search.domain.search_domain import RetrievedChunk


def test_suggestion_validator_valid_fix_bug():
    validator = SuggestionValidator()
    chunks = [
        RetrievedChunk(
            chunk_hash="h1",
            file_path="app/crud/appointment.py",
            content="def create_appointment(db, appointment_data):\n    return Appointment(**appointment_data)",
            score=0.9,
        )
    ]
    analysis = {
        "current_behavior": "Missing appointment_date field",
        "likely_cause": "Field not passed to constructor",
        "proposed_fix": "Add appointment_date=appointment_data.appointment_date",
        "proposed_change": "Pass appointment_date to Appointment model",
    }
    result = validator.validate(analysis, chunks)
    assert isinstance(result, ValidationResult)
    assert result.is_valid is True
    assert result.status == "passed"
    assert result.errors == []


def test_suggestion_validator_uncertainty_marker():
    validator = SuggestionValidator()
    chunks = [
        RetrievedChunk(
            chunk_hash="h1",
            file_path="app/crud/appointment.py",
            content="code",
            score=0.9,
        )
    ]
    analysis = {
        "current_behavior": "Wait, let me re-read the code to be sure",
        "proposed_fix": "Fix something",
    }
    result = validator.validate(analysis, chunks)
    assert isinstance(result, ValidationResult)
    assert result.is_valid is False
    assert result.status == "failed"
