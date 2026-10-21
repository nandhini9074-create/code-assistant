"""
tests/unit/evaluation/test_schemas.py
Unit tests for evaluation data models and schemas.
"""

import pytest
from pydantic import ValidationError

from app.core.enums import IntentType
from evaluation.schemas import (
    EvaluationDataset,
    EvaluationItem,
    RelevantChunk,
    ValidationErrorDetail,
    ValidationResult,
)


def test_relevant_chunk_creation_valid():
    """Verify valid RelevantChunk initialization."""
    chunk = RelevantChunk(
        chunk_id="hash_123",
        relevance_grade=3.0,
        file_path="src/main.py",
        symbol_name="login",
        metadata={"author": "alice"},
    )
    assert chunk.chunk_id == "hash_123"
    assert chunk.relevance_grade == 3.0
    assert chunk.file_path == "src/main.py"
    assert chunk.symbol_name == "login"
    assert chunk.metadata["author"] == "alice"


def test_relevant_chunk_without_chunk_id_valid():
    """Verify RelevantChunk can be created with file_path and symbol_name without chunk_id."""
    chunk = RelevantChunk(
        file_path="app/routers/appointments.py",
        symbol_name="suggest_time",
        relevance_grade=3.0,
    )
    assert chunk.chunk_id is None
    assert chunk.file_path == "app/routers/appointments.py"
    assert chunk.symbol_name == "suggest_time"
    assert chunk.relevance_grade == 3.0
    assert chunk.identifier == "app/routers/appointments.py::suggest_time"


def test_relevant_chunk_fallback_symbol_unavailable():
    """Verify RelevantChunk identifier falls back to file_path when symbol_name is omitted."""
    chunk = RelevantChunk(
        file_path="app/models/appointment.py",
        relevance_grade=2.0,
    )
    assert chunk.chunk_id is None
    assert chunk.symbol_name is None
    assert chunk.identifier == "app/models/appointment.py"


def test_relevant_chunk_rejects_missing_both_id_and_file_path():
    """Verify RelevantChunk rejects when neither chunk_id nor file_path is provided."""
    with pytest.raises(ValidationError):
        RelevantChunk(relevance_grade=2.0)


def test_relevant_chunk_rejects_empty_id():
    """Verify RelevantChunk rejects empty or whitespace-only chunk_id when no file_path given."""
    with pytest.raises(ValidationError):
        RelevantChunk(chunk_id="", relevance_grade=1.0)

    with pytest.raises(ValidationError):
        RelevantChunk(chunk_id="   ", relevance_grade=1.0)


def test_relevant_chunk_rejects_negative_or_non_numeric_grade():
    """Verify RelevantChunk rejects negative or non-numeric grades."""
    with pytest.raises(ValidationError):
        RelevantChunk(chunk_id="chunk_1", relevance_grade=-1.0)

    with pytest.raises(ValidationError):
        RelevantChunk(chunk_id="chunk_1", relevance_grade="not-a-number")


@pytest.mark.parametrize(
    "intent_str, expected_enum",
    [
        ("RETRIEVE", IntentType.RETRIEVE),
        ("ADD_FEATURE", IntentType.ADD_FEATURE),
        ("FIX_BUG", IntentType.FIX_BUG),
        ("OPTIMIZE", IntentType.OPTIMIZE),
        ("REFACTOR", IntentType.REFACTOR),
        ("FIX_VULNERABILITY", IntentType.FIX_VULNERABILITY),
        ("retrieve", IntentType.RETRIEVE),
        ("fix_vulnerability", IntentType.FIX_VULNERABILITY),
    ],
)
def test_evaluation_item_supports_all_six_intents(intent_str, expected_enum):
    """Verify that all six canonical RepoLens intents are properly accepted and normalized."""
    item = EvaluationItem(
        query_id="q-test",
        query="test query",
        expected_intent=intent_str,
    )
    assert item.expected_intent == expected_enum


def test_evaluation_item_rejects_invalid_intent():
    """Verify EvaluationItem rejects unsupported intent names."""
    with pytest.raises(ValidationError) as exc_info:
        EvaluationItem(
            query_id="q-test",
            query="test query",
            expected_intent="UNSUPPORTED_INTENT",
        )
    assert "Invalid intent" in str(exc_info.value)


def test_evaluation_item_coerces_chunks_from_strings():
    """Verify expected_chunks accepts a list of chunk ID strings."""
    item = EvaluationItem(
        query_id="q-01",
        query="search query",
        expected_intent="RETRIEVE",
        expected_chunks=["chunk_a", "chunk_b"],
    )
    assert len(item.expected_chunks) == 2
    assert item.expected_chunks[0].chunk_id == "chunk_a"
    assert item.expected_chunks[0].relevance_grade == 1.0
    assert item.expected_chunks[1].chunk_id == "chunk_b"


def test_evaluation_item_coerces_chunks_from_dict():
    """Verify expected_chunks accepts a dictionary mapping chunk_id to grade."""
    item = EvaluationItem(
        query_id="q-02",
        query="search query",
        expected_intent="FIX_BUG",
        expected_chunks={"chunk_primary": 3.0, "chunk_secondary": 1.5},
    )
    assert len(item.expected_chunks) == 2
    grades = {c.chunk_id: c.relevance_grade for c in item.expected_chunks}
    assert grades["chunk_primary"] == 3.0
    assert grades["chunk_secondary"] == 1.5


def test_evaluation_item_rejects_empty_query_or_id():
    """Verify empty query or query_id is rejected."""
    with pytest.raises(ValidationError):
        EvaluationItem(query_id="", query="some query", expected_intent="RETRIEVE")

    with pytest.raises(ValidationError):
        EvaluationItem(query_id="q1", query="   ", expected_intent="RETRIEVE")


def test_evaluation_dataset_methods():
    """Verify EvaluationDataset helper methods (get_by_id, filter_by_intent, to_json, to_jsonl)."""
    item1 = EvaluationItem(
        query_id="q1",
        query="query 1",
        expected_intent=IntentType.RETRIEVE,
    )
    item2 = EvaluationItem(
        query_id="q2",
        query="query 2",
        expected_intent=IntentType.FIX_BUG,
    )

    dataset = EvaluationDataset(
        dataset_name="Test-Dataset",
        items=[item1, item2],
    )

    assert len(dataset) == 2
    assert dataset[0].query_id == "q1"
    assert dataset.get_by_id("q1") == item1
    assert dataset.get_by_id("non-existent") is None

    bug_items = dataset.filter_by_intent(IntentType.FIX_BUG)
    assert len(bug_items) == 1
    assert bug_items[0].query_id == "q2"

    # Serialization
    json_repr = dataset.to_json()
    assert "Test-Dataset" in json_repr
    assert "q1" in json_repr

    jsonl_repr = dataset.to_jsonl()
    lines = jsonl_repr.splitlines()
    assert len(lines) == 2
    assert "q1" in lines[0]
    assert "q2" in lines[1]
