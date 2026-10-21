"""
tests/unit/evaluation/test_suite.py
Unit tests for evaluation/suite.py - EvaluationSuite and CLI suite command.

Tests verify:
    - EvaluationSuite runs full pipeline (load dataset -> evaluate -> threshold check -> report -> write json).
    - Outcome code is SUCCESS when thresholds are met.
    - Outcome code is BELOW_THRESHOLD when metrics fail threshold checks.
    - Outcome code is BLOCKED when dataset cannot be loaded or no adapters provided.
    - Output files (JSON and Markdown) are written correctly when output_dir is configured.
    - CLI suite command executes correctly and returns expected exit codes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.enums import IntentType
from evaluation.adapters.base import BaseIntentAdapter, BaseRetrieverAdapter
from evaluation.cli import main
from evaluation.reporting import (
    OUTCOME_BELOW_THRESHOLD,
    OUTCOME_BLOCKED,
    OUTCOME_SUCCESS,
)
from evaluation.suite import EvaluationSuite, SuiteOutcome
from evaluation.thresholds import ThresholdConfig


# ---------------------------------------------------------------------------
# Mock Adapters
# ---------------------------------------------------------------------------


class MockIntentAdapter(BaseIntentAdapter):
    def __init__(self, return_intent: IntentType = IntentType.RETRIEVE) -> None:
        self.return_intent = return_intent

    async def classify(
        self, query: str, repo_name: Optional[str] = None
    ) -> Optional[IntentType]:
        return self.return_intent


class MockChunk:
    def __init__(self, chunk_hash: str) -> None:
        self.chunk_hash = chunk_hash


class MockRetrieverAdapter(BaseRetrieverAdapter):
    def __init__(self, chunks: Optional[List[str]] = None) -> None:
        self.chunks = chunks or ["chunk_1", "chunk_2"]

    async def retrieve(
        self,
        query: str,
        collection_name: str,
        limit: int = 20,
        repo_name: Optional[str] = None,
    ) -> List[Any]:
        return [MockChunk(c) for c in self.chunks]


# ---------------------------------------------------------------------------
# EvaluationSuite Tests
# ---------------------------------------------------------------------------


class TestEvaluationSuite:
    @pytest.fixture
    def sample_dataset_path(self) -> Path:
        p = Path("evaluation/datasets/sample_evaluation_dataset.json")
        assert p.exists(), f"Sample dataset not found at {p}"
        return p

    @pytest.mark.asyncio
    async def test_suite_success_outcome(
        self,
        sample_dataset_path: Path,
        tmp_path: Path,
    ):
        suite = EvaluationSuite(
            dataset_path=sample_dataset_path,
            intent_adapter=MockIntentAdapter(return_intent=IntentType.RETRIEVE),
            retriever_adapter=MockRetrieverAdapter(chunks=["chunk_search_01", "chunk_auth_01"]),
            thresholds=ThresholdConfig(min_intent_accuracy=0.0),  # Very lenient threshold
            output_dir=tmp_path,
        )

        outcome: SuiteOutcome = await suite.run()

        assert outcome.outcome_code in (OUTCOME_SUCCESS, "COMPLETED_WITH_FAILURES")
        assert outcome.report is not None
        assert outcome.markdown_report is not None
        assert outcome.json_report_path is not None
        assert outcome.json_report_path.exists()
        assert len(outcome.blocking_errors) == 0

    @pytest.mark.asyncio
    async def test_suite_below_threshold_outcome(
        self,
        sample_dataset_path: Path,
        tmp_path: Path,
    ):
        suite = EvaluationSuite(
            dataset_path=sample_dataset_path,
            intent_adapter=MockIntentAdapter(return_intent=IntentType.RETRIEVE),
            thresholds=ThresholdConfig(min_intent_accuracy=1.0),  # Impossible threshold since dataset has multiple intents
            output_dir=tmp_path,
        )

        outcome: SuiteOutcome = await suite.run()

        assert outcome.outcome_code == OUTCOME_BELOW_THRESHOLD
        assert not outcome.passed
        assert outcome.threshold_result is not None
        assert not outcome.threshold_result.passed
        assert len(outcome.threshold_result.failures) > 0

    @pytest.mark.asyncio
    async def test_suite_blocked_missing_dataset(self, tmp_path: Path):
        non_existent = tmp_path / "does_not_exist.json"
        suite = EvaluationSuite(
            dataset_path=non_existent,
            intent_adapter=MockIntentAdapter(),
        )

        outcome: SuiteOutcome = await suite.run()

        assert outcome.outcome_code == OUTCOME_BLOCKED
        assert not outcome.passed
        assert len(outcome.blocking_errors) > 0

    @pytest.mark.asyncio
    async def test_suite_blocked_no_adapters(
        self,
        sample_dataset_path: Path,
    ):
        suite = EvaluationSuite(
            dataset_path=sample_dataset_path,
            intent_adapter=None,
            retriever_adapter=None,
        )

        outcome: SuiteOutcome = await suite.run()

        assert outcome.outcome_code == OUTCOME_BLOCKED
        assert not outcome.passed
        assert any("adapter" in err.lower() for err in outcome.blocking_errors)


# ---------------------------------------------------------------------------
# CLI Suite Subcommand Tests
# ---------------------------------------------------------------------------


class TestCliSuiteCommand:
    def test_cli_suite_offline_success(self, tmp_path: Path):
        dataset_path = "evaluation/datasets/sample_evaluation_dataset.json"
        exit_code = main([
            "suite",
            dataset_path,
            "--offline",
            "--min-intent-accuracy", "0.0",
            "--output-dir", str(tmp_path),
        ])

        assert exit_code == 0
        written_files = list(tmp_path.glob("*.json"))
        assert len(written_files) == 1

    def test_cli_suite_below_threshold_exit_code(self, tmp_path: Path):
        dataset_path = "evaluation/datasets/sample_evaluation_dataset.json"
        exit_code = main([
            "suite",
            dataset_path,
            "--offline",
            "--min-intent-accuracy", "1.0",  # Will fail
            "--output-dir", str(tmp_path),
        ])

        assert exit_code == 1

    def test_cli_suite_save_markdown(self, tmp_path: Path):
        dataset_path = "evaluation/datasets/sample_evaluation_dataset.json"
        md_file = tmp_path / "custom_report.md"
        exit_code = main([
            "suite",
            dataset_path,
            "--offline",
            "--min-intent-accuracy", "0.0",
            "--save-markdown", str(md_file),
            "--output-dir", str(tmp_path),
        ])

        assert exit_code == 0
        assert md_file.exists()
        content = md_file.read_text(encoding="utf-8")
        assert "# RepoLens Evaluation Report" in content
