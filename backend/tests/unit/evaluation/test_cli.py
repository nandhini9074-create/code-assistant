"""
tests/unit/evaluation/test_cli.py
Unit tests for the evaluation CLI interface.
"""

import json
from pathlib import Path

from evaluation.cli import main


def test_cli_help(capsys):
    """Verify CLI prints help and exits with 0."""
    code = main([])
    captured = capsys.readouterr()
    assert code == 0
    assert "RepoLens AI Code Search Assistant - Evaluation CLI" in captured.out


def test_cli_validate_success(tmp_path: Path, capsys):
    """Verify CLI validate command succeeds on valid dataset."""
    valid_file = tmp_path / "valid.json"
    valid_data = [
        {"query_id": "q1", "query": "Find route", "expected_intent": "RETRIEVE"},
        {"query_id": "q2", "query": "Fix memory leak", "expected_intent": "FIX_BUG"},
    ]
    valid_file.write_text(json.dumps(valid_data), encoding="utf-8")

    code = main(["validate", str(valid_file)])
    captured = capsys.readouterr()

    assert code == 0
    assert "PASSED" in captured.out
    assert "Total Items:            2" in captured.out
    assert "[SUCCESS]" in captured.out


def test_cli_validate_failure_on_invalid_data(tmp_path: Path, capsys):
    """Verify CLI validate command fails on invalid dataset."""
    invalid_file = tmp_path / "invalid.json"
    invalid_data = [
        {"query_id": "q1", "query": "Where is config?", "expected_intent": "INVALID_INTENT"},
        {"query_id": "q1", "query": "Duplicate ID", "expected_intent": "RETRIEVE"},
    ]
    invalid_file.write_text(json.dumps(invalid_data), encoding="utf-8")

    code = main(["validate", str(invalid_file)])
    captured = capsys.readouterr()

    assert code == 1
    assert "FAILED" in captured.out
    assert "[ERROR]" in captured.out
    assert "INVALID_INTENT" in captured.out
    assert "DUPLICATE_QUERY_ID" in captured.out


def test_cli_validate_missing_file(capsys):
    """Verify CLI validate command exits with 1 on non-existent file."""
    code = main(["validate", "non_existent_file.json"])
    captured = capsys.readouterr()
    assert code == 1
    assert "[ERROR] Failed to load dataset" in captured.out



def test_cli_convert_command(tmp_path: Path, capsys):
    """Verify CLI convert command transforms JSON dataset to JSONL."""
    json_in = tmp_path / "input.json"
    jsonl_out = tmp_path / "output.jsonl"

    data = [
        {"query_id": "qc-1", "query": "Find parser", "expected_intent": "RETRIEVE"},
        {"query_id": "qc-2", "query": "Fix exception", "expected_intent": "FIX_BUG"},
    ]
    json_in.write_text(json.dumps(data), encoding="utf-8")

    code = main(["convert", str(json_in), str(jsonl_out)])
    captured = capsys.readouterr()

    assert code == 0
    assert "[SUCCESS] Converted 2 items" in captured.out
    assert jsonl_out.exists()

    lines = [json.loads(line) for line in jsonl_out.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2
    assert lines[0]["query_id"] == "qc-1"
    assert lines[1]["query_id"] == "qc-2"
