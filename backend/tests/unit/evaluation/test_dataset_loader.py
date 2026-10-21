"""
tests/unit/evaluation/test_dataset_loader.py
Unit tests for dataset loading, deserialization, and serialization.
"""

import json
from pathlib import Path
import pytest

from evaluation.dataset import DatasetLoader
from evaluation.exceptions import DatasetLoadError, DatasetValidationError
from evaluation.schemas import EvaluationDataset, EvaluationItem


def test_loader_load_json_object_format(tmp_path: Path):
    """Verify loading dataset from JSON object with top-level metadata and items."""
    json_path = tmp_path / "dataset.json"
    data = {
        "dataset_name": "Custom-Benchmark",
        "version": "2.0",
        "description": "A test dataset",
        "items": [
            {
                "query_id": "q1",
                "query": "Where is the router?",
                "expected_intent": "RETRIEVE",
                "expected_chunks": ["chunk_route_1"],
            }
        ],
    }
    json_path.write_text(json.dumps(data), encoding="utf-8")

    loader = DatasetLoader()
    dataset = loader.load_from_file(json_path)

    assert isinstance(dataset, EvaluationDataset)
    assert dataset.dataset_name == "Custom-Benchmark"
    assert dataset.version == "2.0"
    assert len(dataset) == 1
    assert dataset[0].query_id == "q1"


def test_loader_load_json_array_format(tmp_path: Path):
    """Verify loading dataset from top-level JSON array."""
    json_path = tmp_path / "array_dataset.json"
    items = [
        {"query_id": "q1", "query": "Add user signup", "expected_intent": "ADD_FEATURE"},
        {"query_id": "q2", "query": "Fix login crash", "expected_intent": "FIX_BUG"},
    ]
    json_path.write_text(json.dumps(items), encoding="utf-8")

    loader = DatasetLoader()
    dataset = loader.load_from_file(json_path)

    assert len(dataset) == 2
    assert dataset[0].expected_intent.value == "ADD_FEATURE"
    assert dataset[1].expected_intent.value == "FIX_BUG"


def test_loader_load_jsonl_format(tmp_path: Path):
    """Verify loading dataset from JSON Lines file."""
    jsonl_path = tmp_path / "dataset.jsonl"
    lines = [
        json.dumps({"query_id": "ql-1", "query": "Search files", "expected_intent": "RETRIEVE"}),
    ]
    jsonl_path.write_text("\n".join(lines), encoding="utf-8")

    loader = DatasetLoader()
    dataset = loader.load_from_file(jsonl_path)

    assert len(dataset) == 2
    assert dataset[0].query_id == "ql-1"
    assert dataset[1].expected_intent.value == "REFACTOR"


def test_loader_rejects_missing_file():
    """Verify DatasetLoadError is raised when file does not exist."""
    loader = DatasetLoader()
    with pytest.raises(DatasetLoadError) as exc_info:
        loader.load_from_file("non_existent_file_path.json")
    assert "not found" in str(exc_info.value)


def test_loader_rejects_malformed_json(tmp_path: Path):
    """Verify DatasetLoadError is raised on syntax errors in JSON."""
    bad_json_path = tmp_path / "bad.json"
    bad_json_path.write_text("{ unquoted_key: 123 ", encoding="utf-8")

    loader = DatasetLoader()
    with pytest.raises(DatasetLoadError) as exc_info:
        loader.load_from_file(bad_json_path)
    assert "Malformed JSON" in str(exc_info.value)


def test_loader_rejects_malformed_jsonl(tmp_path: Path):
    """Verify DatasetLoadError is raised on syntax errors in JSONL lines."""
    bad_jsonl_path = tmp_path / "bad.jsonl"
    bad_jsonl_path.write_text(
        '{"query_id": "ok", "query": "ok", "expected_intent": "RETRIEVE"}\n{ invalid json line }\n',
        encoding="utf-8",
    )

    loader = DatasetLoader()
    with pytest.raises(DatasetLoadError) as exc_info:
        loader.load_from_file(bad_jsonl_path)
    assert "line 2" in str(exc_info.value)


def test_loader_strict_validation_error_on_invalid_data(tmp_path: Path):
    """Verify DatasetValidationError is raised in strict mode when records contain invalid fields."""
    invalid_path = tmp_path / "invalid_records.json"
    bad_records = [
        {"query_id": "q1", "query": "Test", "expected_intent": "INVALID_INTENT"}
    ]
    invalid_path.write_text(json.dumps(bad_records), encoding="utf-8")

    loader = DatasetLoader()
    with pytest.raises(DatasetValidationError) as exc_info:
        loader.load_from_file(invalid_path, strict=True)
    assert "validation failed" in str(exc_info.value).lower()


def test_loader_save_and_reload_roundtrip(tmp_path: Path):
    """Verify dataset can be saved to file as JSON and reloaded without data loss."""
    dataset = EvaluationDataset(
        dataset_name="Roundtrip-Benchmark",
        version="1.5",
        description="Testing roundtrip persistence",
        items=[
            EvaluationItem(
                query_id="rt-1",
                query="Find cache manager",
                expected_intent="RETRIEVE",
                repository="repolens",
                collection_name="repo_local_repolens",
                expected_chunks=["chunk_cache_01"],
            )
        ],
    )

    save_path = tmp_path / "saved_benchmark.json"
    loader = DatasetLoader()
    loader.save_to_file(dataset, save_path)

    assert save_path.exists()
    reloaded = loader.load_from_file(save_path)

    assert reloaded.dataset_name == "Roundtrip-Benchmark"
    assert reloaded.version == "1.5"
    assert len(reloaded) == 1
    assert reloaded[0].query_id == "rt-1"
    assert reloaded[0].expected_chunks[0].chunk_id == "chunk_cache_01"


def test_sample_datasets_on_disk():
    """Verify that the built-in reference sample datasets (JSON & JSONL) load cleanly."""
    loader = DatasetLoader()
    datasets_dir = Path(__file__).resolve().parents[3] / "evaluation" / "datasets"

    json_file = datasets_dir / "sample_evaluation_dataset.json"
    jsonl_file = datasets_dir / "sample_evaluation_dataset.jsonl"

    assert json_file.exists(), f"Sample dataset {json_file} does not exist"
    assert jsonl_file.exists(), f"Sample dataset {jsonl_file} does not exist"

    dataset_json = loader.load_from_file(json_file, strict=True)
    assert len(dataset_json) == 6

    dataset_jsonl = loader.load_from_file(jsonl_file, strict=True)
    assert len(dataset_jsonl) >= 6
