"""Unit tests for CodeExistenceValidator."""

from app.modules.code_analysis.domain.analysis_domain import ValidationResult
from app.modules.code_analysis.validators.code_existence_validator import (
    CodeExistenceValidator,
)
from app.modules.search.domain.search_domain import RetrievedChunk


def test_code_existence_validator_returns_validation_result_on_valid_match():
    validator = CodeExistenceValidator()
    chunks = [
        RetrievedChunk(
            chunk_hash="h1",
            file_path="app/crud/appointment.py",
            content="def create_appointment(db, appointment_data):\n    return Appointment(**appointment_data)",
            score=0.9,
        )
    ]
    analysis = {
        "problematic_code": "def create_appointment(db, appointment_data):",
    }
    result = validator.validate(analysis, chunks)
    assert isinstance(result, ValidationResult)
    assert result.is_valid is True
    assert result.status == "passed"
    assert result.errors == []


def test_code_existence_validator_detects_missing_code():
    validator = CodeExistenceValidator()
    chunks = [
        RetrievedChunk(
            chunk_hash="h1",
            file_path="app/crud/appointment.py",
            content="def create_appointment(db, appointment_data):\n    return Appointment(**appointment_data)",
            score=0.9,
        )
    ]
    analysis = {
        "problematic_code": "some_completely_nonexistent_function_xyz_123()",
    }
    result = validator.validate(analysis, chunks)
    assert isinstance(result, ValidationResult)
    assert result.is_valid is False
    assert result.status == "failed"
    assert len(result.errors) > 0
