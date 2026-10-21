"""
tests/unit/evaluation/test_dataset_validator.py
Unit tests for evaluation dataset validator.
"""

import pytest

from app.core.enums import IntentType
from evaluation.config import EvaluationConfig
from evaluation.dataset import DatasetValidator
from evaluation.exceptions import DatasetValidationError
from evaluation.schemas import EvaluationDataset, EvaluationItem


def test_validator_passes_on_valid_records():
    """Verify DatasetValidator passes on a completely valid dataset."""
    validator = DatasetValidator()
    records = [
        {
            "query_id": "q-01",
            "query": "Where is the auth handler?",
            "expected_intent": "RETRIEVE",
            "expected_chunks": ["chunk_01"],
        },
        {
            "query_id": "q-02",
            "query": "Fix database connection leak",
            "expected_intent": "FIX_BUG",
            "expected_chunks": [{"chunk_id": "chunk_02", "relevance_grade": 2.0}],
        },
    ]

    result = validator.validate_raw_records(records)
    assert result.is_valid is True
    assert len(result.errors) == 0
    assert result.total_items == 2
    assert result.queries_with_chunks == 2
    assert result.total_relevant_chunks == 2
    assert result.intent_distribution["RETRIEVE"] == 1
    assert result.intent_distribution["FIX_BUG"] == 1


def test_validator_detects_missing_mandatory_fields():
    """Verify DatasetValidator detects missing query_id, query, or expected_intent."""
    validator = DatasetValidator()
    records = [
        {"query": "Where is X?", "expected_intent": "RETRIEVE"},  # missing query_id
        {"query_id": "q-02", "expected_intent": "RETRIEVE"},       # missing query
        {"query_id": "q-03", "query": "Fix bug"},                  # missing expected_intent
    ]

    result = validator.validate_raw_records(records)
    assert result.is_valid is False
    assert len(result.errors) == 3

    error_fields = {e.field for e in result.errors}
    assert "query_id" in error_fields
    assert "query" in error_fields
    assert "expected_intent" in error_fields

    error_types = {e.error_type for e in result.errors}
    assert "MISSING_FIELD" in error_types


def test_validator_detects_invalid_intent():
    """Verify DatasetValidator flags unrecognized intents."""
    validator = DatasetValidator()
    records = [
        {
            "query_id": "q-01",
            "query": "Explain this function",
            "expected_intent": "EXPLAIN_CODE",  # Unsupported intent
        }
    ]

    result = validator.validate_raw_records(records)
    assert result.is_valid is False
    assert len(result.errors) == 1
    assert result.errors[0].error_type == "INVALID_INTENT"
    assert "EXPLAIN_CODE" in result.errors[0].message


def test_validator_detects_duplicate_query_ids():
    """Verify DatasetValidator catches duplicate query_id entries."""
    validator = DatasetValidator()
    records = [
        {"query_id": "q-duplicate", "query": "First query", "expected_intent": "RETRIEVE"},
        {"query_id": "q-duplicate", "query": "Second query", "expected_intent": "FIX_BUG"},
    ]

    result = validator.validate_raw_records(records)
    assert result.is_valid is False
    assert any(e.error_type == "DUPLICATE_QUERY_ID" for e in result.errors)


def test_validator_detects_invalid_relevance_grades():
    """Verify DatasetValidator flags negative, non-numeric, or out-of-range grades."""
    custom_config = EvaluationConfig(min_relevance_grade=0.0, max_relevance_grade=3.0)
    validator = DatasetValidator(config=custom_config)

    records = [
        {
            "query_id": "q-01",
            "query": "Find parser",
            "expected_intent": "RETRIEVE",
            "expected_chunks": [
                {"chunk_id": "c1", "relevance_grade": -2.0},      # Negative grade
                {"chunk_id": "c2", "relevance_grade": "invalid"},   # Non-numeric
                {"chunk_id": "c3", "relevance_grade": 5.0},         # Exceeds max (3.0)
            ],
        }
    ]

    result = validator.validate_raw_records(records)
    assert result.is_valid is False
    assert len(result.errors) == 3
    for err in result.errors:
        assert err.error_type == "INVALID_RELEVANCE_GRADE"


def test_validator_detects_empty_chunk_ids():
    """Verify DatasetValidator catches empty or whitespace chunk IDs."""
    validator = DatasetValidator()
    records = [
        {
            "query_id": "q-01",
            "query": "Find parser",
            "expected_intent": "RETRIEVE",
            "expected_chunks": [{"chunk_id": "   ", "relevance_grade": 1.0}],
        }
    ]

    result = validator.validate_raw_records(records)
    assert result.is_valid is False
    assert any(e.error_type == "INVALID_CHUNK_ID" for e in result.errors)


def test_validation_result_raise_for_status():
    """Verify ValidationResult.raise_for_status raises DatasetValidationError when invalid."""
    validator = DatasetValidator()
    bad_records = [{"query_id": "q1"}]  # missing query and intent
    result = validator.validate_raw_records(bad_records)

    with pytest.raises(DatasetValidationError) as exc_info:
        result.raise_for_status()

    assert "Dataset validation failed" in str(exc_info.value)
    assert exc_info.value.validation_result == result


def test_validator_on_evaluation_dataset_instance():
    """Verify DatasetValidator.validate works on an instantiated EvaluationDataset object."""
    item = EvaluationItem(
        query_id="q-ok",
        query="query text",
        expected_intent=IntentType.OPTIMIZE,
        expected_chunks=["chunk_perf_01"],
    )
    dataset = EvaluationDataset(items=[item])

    validator = DatasetValidator()
    result = validator.validate(dataset)
    assert result.is_valid is True
    assert result.intent_distribution["OPTIMIZE"] == 1


def test_validator_passes_on_chunks_without_chunk_id():
    """Verify DatasetValidator accepts chunks with file_path and symbol_name (no chunk_id)."""
    validator = DatasetValidator()
    records = [
        {
            "query_id": "q-hosp-01",
            "query": "Where is appointment time suggestion implemented?",
            "expected_intent": "RETRIEVE",
            "expected_chunks": [
                {
                    "file_path": "app/routers/appointments.py",
                    "symbol_name": "suggest_time",
                    "relevance_grade": 3.0,
                },
                {
                    "file_path": "app/crud/appointment.py",
                    "symbol_name": "find_nearest_available_slot",
                    "relevance_grade": 2.0,
                },
            ],
        }
    ]

    result = validator.validate_raw_records(records)
    assert result.is_valid is True
    assert len(result.errors) == 0
    assert result.total_relevant_chunks == 2


def test_validator_detects_missing_relevance_grade():
    """Verify DatasetValidator catches missing relevance_grade in chunk dictionaries."""
    validator = DatasetValidator()
    records = [
        {
            "query_id": "q-01",
            "query": "Find parser",
            "expected_intent": "RETRIEVE",
            "expected_chunks": [
                {"file_path": "app/routers/appointments.py", "symbol_name": "suggest_time"}
            ],
        }
    ]

    result = validator.validate_raw_records(records)
    assert result.is_valid is False
    assert any(e.error_type == "MISSING_RELEVANCE_GRADE" for e in result.errors)


def test_validator_detects_missing_both_chunk_id_and_file_path():
    """Verify DatasetValidator catches chunk dict missing both chunk_id and file_path."""
    validator = DatasetValidator()
    records = [
        {
            "query_id": "q-01",
            "query": "Find parser",
            "expected_intent": "RETRIEVE",
            "expected_chunks": [{"relevance_grade": 2.0}],
        }
    ]

    result = validator.validate_raw_records(records)
    assert result.is_valid is False
    assert any(e.error_type == "INVALID_CHUNK_ID" for e in result.errors)
