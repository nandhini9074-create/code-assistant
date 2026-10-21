"""
tests/unit/evaluation/test_reporting.py
Unit tests for evaluation/reporting.py - MarkdownReportRenderer and VersionedJsonWriter.

Tests verify:
    - MarkdownReportRenderer renders run metadata, health summary, retrieval table,
      intent table, confusion matrix, threshold section, and guidance notes.
    - Outcome code resolution: SUCCESS, BELOW_THRESHOLD, COMPLETED_WITH_FAILURES, BLOCKED.
    - VersionedJsonWriter writes valid JSON containing schema_version, outcome, timestamp,
      and serialized evaluation and threshold results.
    - VersionedJsonWriter handles custom extra_metadata.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.reporting import (
    OUTCOME_BELOW_THRESHOLD,
    OUTCOME_BLOCKED,
    OUTCOME_FAILURES,
    OUTCOME_SUCCESS,
    REPORT_SCHEMA_VERSION,
    MarkdownReportRenderer,
    VersionedJsonWriter,
)
from evaluation.results import (
    EvaluationReport,
    IntentEvaluationReport,
    QueryRetrievalResult,
    RetrievalEvaluationReport,
)
from evaluation.thresholds import (
    ThresholdConfig,
    ThresholdFailure,
    ThresholdResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_retrieval_report() -> RetrievalEvaluationReport:
    return RetrievalEvaluationReport(
        dataset_name="test_dataset",
        total_queries=2,
        evaluated_queries=2,
        failed_queries=0,
        k=5,
        mean_recall_at_k=0.85,
        mean_precision_at_k=0.60,
        mrr=0.75,
        mean_ndcg_at_k=0.80,
        per_query=[
            QueryRetrievalResult(
                query_id="q1",
                query="Find auth middleware",
                collection_name="test_coll",
                retrieved_chunk_ids=["c1", "c2"],
                relevant_chunk_ids=["c1"],
                recall_at_k=1.0,
                precision_at_k=0.5,
                reciprocal_rank=1.0,
                ndcg_at_k=1.0,
            ),
            QueryRetrievalResult(
                query_id="q2",
                query="Find db connection",
                collection_name="test_coll",
                retrieved_chunk_ids=["c3"],
                relevant_chunk_ids=["c4"],
                recall_at_k=0.0,
                precision_at_k=0.0,
                reciprocal_rank=0.0,
                ndcg_at_k=0.0,
            ),
        ],
    )


@pytest.fixture
def sample_intent_report() -> IntentEvaluationReport:
    return IntentEvaluationReport(
        dataset_name="test_dataset",
        total_queries=3,
        evaluated_queries=3,
        failed_queries=0,
        accuracy=0.6667,
        per_class_metrics={
            "RETRIEVE": {
                "support": 2.0,
                "precision": 0.6667,
                "recall": 1.0,
                "f1": 0.8,
            },
            "FIX_BUG": {
                "support": 1.0,
                "precision": 0.0,
                "recall": 0.0,
                "f1": 0.0,
            },
        },
        confusion_matrix={
            "RETRIEVE": {"RETRIEVE": 2, "FIX_BUG": 0},
            "FIX_BUG": {"RETRIEVE": 1, "FIX_BUG": 0},
        },
    )


@pytest.fixture
def sample_combined_report(
    sample_retrieval_report: RetrievalEvaluationReport,
    sample_intent_report: IntentEvaluationReport,
) -> EvaluationReport:
    return EvaluationReport(
        dataset_name="sample_benchmark",
        retrieval=sample_retrieval_report,
        intent=sample_intent_report,
    )


# ---------------------------------------------------------------------------
# Outcome Resolution Tests
# ---------------------------------------------------------------------------


class TestOutcomeResolution:
    def test_outcome_blocked_when_both_none(self):
        report = EvaluationReport(
            dataset_name="empty",
            retrieval=None,
            intent=None,
        )
        assert MarkdownReportRenderer._resolve_outcome(report, None) == OUTCOME_BLOCKED

    def test_outcome_below_threshold(
        self,
        sample_combined_report: EvaluationReport,
    ):
        failed_thresh = ThresholdResult(
            passed=False,
            failures=[
                ThresholdFailure(
                    metric="recall@5",
                    actual=0.85,
                    threshold=0.90,
                    message="recall@5 (0.8500) < min_recall_at_k (0.9000)",
                )
            ],
            warnings=[],
            checked_metrics={"recall@5": 0.85},
        )
        assert (
            MarkdownReportRenderer._resolve_outcome(sample_combined_report, failed_thresh)
            == OUTCOME_BELOW_THRESHOLD
        )

    def test_outcome_failures_when_errors_present(
        self,
        sample_retrieval_report: RetrievalEvaluationReport,
        sample_intent_report: IntentEvaluationReport,
    ):
        sample_retrieval_report.failed_queries = 1
        report = EvaluationReport(
            dataset_name="bench",
            retrieval=sample_retrieval_report,
            intent=sample_intent_report,
        )
        passed_thresh = ThresholdResult(
            passed=True,
            failures=[],
            warnings=[],
            checked_metrics={},
        )
        assert MarkdownReportRenderer._resolve_outcome(report, passed_thresh) == OUTCOME_FAILURES

    def test_outcome_success(self, sample_combined_report: EvaluationReport):
        passed_thresh = ThresholdResult(
            passed=True,
            failures=[],
            warnings=[],
            checked_metrics={},
        )
        assert MarkdownReportRenderer._resolve_outcome(sample_combined_report, passed_thresh) == OUTCOME_SUCCESS


# ---------------------------------------------------------------------------
# MarkdownReportRenderer Tests
# ---------------------------------------------------------------------------


class TestMarkdownReportRenderer:
    def test_render_full_report(self, sample_combined_report: EvaluationReport):
        renderer = MarkdownReportRenderer()
        thresh = ThresholdResult(
            passed=True,
            failures=[],
            warnings=["nDCG threshold skipped"],
            checked_metrics={
                "recall@5": 0.85,
                "intent_accuracy": 0.6667,
            },
        )
        config_summary = {"k": 5, "min_recall_at_k": 0.70}

        markdown = renderer.render(
            report=sample_combined_report,
            threshold_result=thresh,
            config_summary=config_summary,
        )

        assert "# RepoLens Evaluation Report" in markdown
        assert "sample_benchmark" in markdown
        assert "SUCCESS" in markdown
        assert "## Dataset Health" in markdown
        assert "## Retrieval Metrics" in markdown
        assert "Precision@5" in markdown
        assert "0.8500" in markdown
        assert "## Intent Classification Metrics" in markdown
        assert "RETRIEVE" in markdown
        assert "FIX_BUG" in markdown
        assert "Confusion Matrix" in markdown
        assert "## Threshold Check" in markdown
        assert "## How to Add New Evaluation Queries" in markdown
        assert "## Known Limitations" in markdown

    def test_render_retrieval_only(self, sample_retrieval_report: RetrievalEvaluationReport):
        report = EvaluationReport(
            dataset_name="retrieval_only",
            retrieval=sample_retrieval_report,
            intent=None,
        )
        renderer = MarkdownReportRenderer()
        markdown = renderer.render(report)

        assert "## Retrieval Metrics" in markdown
        assert "## Intent Classification Metrics" not in markdown

    def test_render_intent_only(self, sample_intent_report: IntentEvaluationReport):
        report = EvaluationReport(
            dataset_name="intent_only",
            retrieval=None,
            intent=sample_intent_report,
        )
        renderer = MarkdownReportRenderer()
        markdown = renderer.render(report)

        assert "## Intent Classification Metrics" in markdown
        assert "## Retrieval Metrics" not in markdown


# ---------------------------------------------------------------------------
# VersionedJsonWriter Tests
# ---------------------------------------------------------------------------


class TestVersionedJsonWriter:
    def test_write_produces_valid_json(
        self,
        tmp_path: Path,
        sample_combined_report: EvaluationReport,
    ):
        writer = VersionedJsonWriter(output_dir=tmp_path)
        thresh = ThresholdResult(
            passed=True,
            failures=[],
            warnings=[],
            checked_metrics={"recall@5": 0.85},
        )

        out_path = writer.write(
            report=sample_combined_report,
            threshold_result=thresh,
            outcome=OUTCOME_SUCCESS,
            extra_metadata={"environment": "ci", "git_commit": "abc1234"},
        )

        assert out_path.exists()
        assert out_path.suffix == ".json"
        assert f"v{REPORT_SCHEMA_VERSION}" in out_path.name
        assert "sample_benchmark" in out_path.name

        data = json.loads(out_path.read_text(encoding="utf-8"))
        assert data["schema_version"] == REPORT_SCHEMA_VERSION
        assert data["outcome"] == OUTCOME_SUCCESS
        assert "generated_at" in data
        assert data["metadata"]["environment"] == "ci"
        assert data["metadata"]["git_commit"] == "abc1234"
        assert data["threshold_check"]["passed"] is True
        assert data["evaluation"]["dataset_name"] == "sample_benchmark"
        assert data["evaluation"]["retrieval"]["mean_recall_at_k"] == 0.85
