"""
tests/unit/evaluation/test_thresholds.py
Unit tests for evaluation/thresholds.py - ThresholdConfig and ThresholdChecker.

Tests verify:
    - All thresholds pass when every metric exceeds its minimum
    - Individual threshold failures are reported correctly
    - nDCG threshold is skipped + warns when nDCG was not computed
    - Failed-query fraction threshold
    - Thresholds are skipped when None (no threshold configured)
    - Macro-F1 is computed from per_class_metrics
    - Thresholds are skipped when the relevant sub-report is missing
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pytest

from evaluation.results import (
    EvaluationReport,
    IntentEvaluationReport,
    QueryIntentResult,
    QueryRetrievalResult,
    RetrievalEvaluationReport,
)
from evaluation.thresholds import ThresholdChecker, ThresholdConfig, ThresholdFailure


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TS = datetime.now(timezone.utc).isoformat()


def make_retrieval_report(
    *,
    precision: float = 0.8,
    recall: float = 0.8,
    mrr: float = 0.8,
    ndcg: Optional[float] = 0.8,
    total: int = 10,
    failed: int = 0,
    skipped: int = 0,
    k: int = 5,
) -> RetrievalEvaluationReport:
    evaluated = total - failed - skipped
    return RetrievalEvaluationReport(
        dataset_name="test",
        evaluated_at=_TS,
        k=k,
        total_queries=total,
        evaluated_queries=evaluated,
        skipped_queries=skipped,
        failed_queries=failed,
        mean_precision_at_k=precision,
        mean_recall_at_k=recall,
        mrr=mrr,
        mean_ndcg_at_k=ndcg,
        per_query=[],
    )


def make_intent_report(
    *,
    accuracy: float = 0.8,
    per_class: Optional[Dict[str, Any]] = None,
    total: int = 10,
    failed: int = 0,
    skipped: int = 0,
) -> IntentEvaluationReport:
    if per_class is None:
        per_class = {
            "RETRIEVE": {"precision": 0.9, "recall": 0.9, "f1": 0.9, "support": 5.0},
            "FIX_BUG":  {"precision": 0.7, "recall": 0.7, "f1": 0.7, "support": 5.0},
        }
    evaluated = total - failed - skipped
    return IntentEvaluationReport(
        dataset_name="test",
        evaluated_at=_TS,
        total_queries=total,
        evaluated_queries=evaluated,
        skipped_queries=skipped,
        failed_queries=failed,
        accuracy=accuracy,
        per_class_metrics=per_class,
        confusion_matrix={},
        per_query=[],
    )


def make_report(
    retrieval: Optional[RetrievalEvaluationReport] = None,
    intent: Optional[IntentEvaluationReport] = None,
) -> EvaluationReport:
    return EvaluationReport(
        dataset_name="test",
        evaluated_at=_TS,
        retrieval=retrieval,
        intent=intent,
    )


# ---------------------------------------------------------------------------
# All thresholds pass
# ---------------------------------------------------------------------------


def test_all_retrieval_thresholds_pass():
    cfg = ThresholdConfig(
        min_recall_at_k=0.6,
        min_precision_at_k=0.6,
        min_mrr=0.6,
        min_ndcg_at_k=0.6,
    )
    report = make_report(retrieval=make_retrieval_report())
    result = ThresholdChecker(cfg).check(report)
    assert result.passed
    assert result.failures == []


def test_all_intent_thresholds_pass():
    cfg = ThresholdConfig(
        min_intent_accuracy=0.7,
        min_intent_macro_f1=0.7,
    )
    report = make_report(intent=make_intent_report())
    result = ThresholdChecker(cfg).check(report)
    assert result.passed
    assert result.failures == []


def test_combined_thresholds_pass():
    cfg = ThresholdConfig(
        min_recall_at_k=0.5,
        min_mrr=0.5,
        min_intent_accuracy=0.5,
    )
    report = make_report(
        retrieval=make_retrieval_report(),
        intent=make_intent_report(),
    )
    result = ThresholdChecker(cfg).check(report)
    assert result.passed


# ---------------------------------------------------------------------------
# Individual threshold failures
# ---------------------------------------------------------------------------


def test_recall_below_threshold():
    cfg = ThresholdConfig(min_recall_at_k=0.9)
    report = make_report(retrieval=make_retrieval_report(recall=0.5))
    result = ThresholdChecker(cfg).check(report)

    assert not result.passed
    assert len(result.failures) == 1
    f = result.failures[0]
    assert f.metric == "mean_recall_at_k"
    assert f.actual == pytest.approx(0.5)
    assert f.threshold == pytest.approx(0.9)


def test_precision_below_threshold():
    cfg = ThresholdConfig(min_precision_at_k=0.9)
    report = make_report(retrieval=make_retrieval_report(precision=0.3))
    result = ThresholdChecker(cfg).check(report)
    assert not result.passed
    assert any(f.metric == "mean_precision_at_k" for f in result.failures)


def test_mrr_below_threshold():
    cfg = ThresholdConfig(min_mrr=0.9)
    report = make_report(retrieval=make_retrieval_report(mrr=0.4))
    result = ThresholdChecker(cfg).check(report)
    assert not result.passed
    assert any(f.metric == "mrr" for f in result.failures)


def test_ndcg_below_threshold():
    cfg = ThresholdConfig(min_ndcg_at_k=0.9)
    report = make_report(retrieval=make_retrieval_report(ndcg=0.2))
    result = ThresholdChecker(cfg).check(report)
    assert not result.passed
    assert any(f.metric == "mean_ndcg_at_k" for f in result.failures)


def test_intent_accuracy_below_threshold():
    cfg = ThresholdConfig(min_intent_accuracy=0.95)
    report = make_report(intent=make_intent_report(accuracy=0.5))
    result = ThresholdChecker(cfg).check(report)
    assert not result.passed
    assert any(f.metric == "intent_accuracy" for f in result.failures)


def test_intent_macro_f1_below_threshold():
    # per-class F1s are 0.9 and 0.7 → macro = 0.8
    cfg = ThresholdConfig(min_intent_macro_f1=0.9)
    report = make_report(intent=make_intent_report())
    result = ThresholdChecker(cfg).check(report)
    assert not result.passed
    assert any(f.metric == "intent_macro_f1" for f in result.failures)


def test_multiple_failures_reported():
    cfg = ThresholdConfig(min_recall_at_k=0.99, min_mrr=0.99)
    report = make_report(retrieval=make_retrieval_report(recall=0.1, mrr=0.1))
    result = ThresholdChecker(cfg).check(report)
    assert not result.passed
    assert len(result.failures) == 2


# ---------------------------------------------------------------------------
# nDCG not available
# ---------------------------------------------------------------------------


def test_ndcg_threshold_warns_when_ndcg_not_computed():
    cfg = ThresholdConfig(min_ndcg_at_k=0.6)
    report = make_report(retrieval=make_retrieval_report(ndcg=None))
    result = ThresholdChecker(cfg).check(report)

    # Should pass (no failure) but warn that nDCG was not checked
    assert result.passed
    assert "mean_ndcg_at_k" in result.skipped_metrics
    assert any("nDCG" in w for w in result.warnings)


def test_ndcg_skipped_when_no_threshold_configured():
    cfg = ThresholdConfig(min_ndcg_at_k=None)
    report = make_report(retrieval=make_retrieval_report(ndcg=0.8))
    result = ThresholdChecker(cfg).check(report)
    assert "mean_ndcg_at_k" in result.skipped_metrics


# ---------------------------------------------------------------------------
# Failed-query fraction
# ---------------------------------------------------------------------------


def test_failed_query_fraction_threshold_pass():
    cfg = ThresholdConfig(max_failed_query_fraction=0.2)
    # 1 failed out of 10 = 10% < 20%
    report = make_report(retrieval=make_retrieval_report(total=10, failed=1))
    result = ThresholdChecker(cfg).check(report)
    assert result.passed


def test_failed_query_fraction_threshold_fail():
    cfg = ThresholdConfig(max_failed_query_fraction=0.05)
    # 3 failed out of 10 = 30% > 5%
    report = make_report(retrieval=make_retrieval_report(total=10, failed=3))
    result = ThresholdChecker(cfg).check(report)
    assert not result.passed
    assert any("failed" in f.metric for f in result.failures)


# ---------------------------------------------------------------------------
# Skipped thresholds when sub-report missing
# ---------------------------------------------------------------------------


def test_retrieval_thresholds_skipped_when_no_retrieval_report():
    cfg = ThresholdConfig(min_recall_at_k=0.6, min_mrr=0.6)
    report = make_report(intent=make_intent_report())  # no retrieval
    result = ThresholdChecker(cfg).check(report)

    # Should not fail (can't check), but should warn
    assert result.passed
    assert len(result.warnings) >= 1


def test_intent_thresholds_skipped_when_no_intent_report():
    cfg = ThresholdConfig(min_intent_accuracy=0.7)
    report = make_report(retrieval=make_retrieval_report())  # no intent
    result = ThresholdChecker(cfg).check(report)

    assert result.passed
    assert len(result.warnings) >= 1


# ---------------------------------------------------------------------------
# Checked metrics dict
# ---------------------------------------------------------------------------


def test_checked_metrics_populated():
    cfg = ThresholdConfig(min_recall_at_k=0.5, min_intent_accuracy=0.5)
    report = make_report(
        retrieval=make_retrieval_report(recall=0.8),
        intent=make_intent_report(accuracy=0.9),
    )
    result = ThresholdChecker(cfg).check(report)
    assert "mean_recall_at_k" in result.checked_metrics
    assert "intent_accuracy" in result.checked_metrics


def test_no_thresholds_configured_all_skipped():
    cfg = ThresholdConfig()  # all None
    report = make_report(
        retrieval=make_retrieval_report(),
        intent=make_intent_report(),
    )
    result = ThresholdChecker(cfg).check(report)
    # Nothing configured → nothing checked → always passes
    assert result.passed
    assert result.checked_metrics == {} or all(
        k in ("intent_macro_f1",) for k in result.checked_metrics
    )


# ---------------------------------------------------------------------------
# Macro F1 computation
# ---------------------------------------------------------------------------


def test_macro_f1_computed_correctly():
    per_class = {
        "A": {"f1": 1.0, "precision": 1.0, "recall": 1.0, "support": 2.0},
        "B": {"f1": 0.5, "precision": 0.5, "recall": 0.5, "support": 2.0},
    }
    # macro F1 = (1.0 + 0.5) / 2 = 0.75
    cfg = ThresholdConfig(min_intent_macro_f1=0.8)
    report = make_report(intent=make_intent_report(per_class=per_class))
    result = ThresholdChecker(cfg).check(report)
    assert not result.passed  # 0.75 < 0.8
    failure = next(f for f in result.failures if f.metric == "intent_macro_f1")
    assert failure.actual == pytest.approx(0.75, abs=1e-6)


def test_macro_f1_passes_correctly():
    per_class = {
        "A": {"f1": 0.9, "precision": 0.9, "recall": 0.9, "support": 3.0},
        "B": {"f1": 0.9, "precision": 0.9, "recall": 0.9, "support": 3.0},
    }
    cfg = ThresholdConfig(min_intent_macro_f1=0.8)
    report = make_report(intent=make_intent_report(per_class=per_class))
    result = ThresholdChecker(cfg).check(report)
    assert result.passed
