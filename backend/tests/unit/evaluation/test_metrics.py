"""
tests/unit/evaluation/test_metrics.py
Unit tests for evaluation/metrics.py.

Tests cover:
    - precision_at_k
    - recall_at_k
    - reciprocal_rank
    - ndcg_at_k
    - mean_reciprocal_rank
    - mean_metric
    - intent_accuracy
    - per_class_intent_metrics
    - intent_confusion_matrix
"""

from __future__ import annotations

import math
import pytest

from evaluation.metrics import (
    extract_chunk_info,
    intent_accuracy,
    intent_confusion_matrix,
    is_chunk_match,
    mean_metric,
    mean_reciprocal_rank,
    ndcg_at_k,
    per_class_intent_metrics,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)


# ---------------------------------------------------------------------------
# precision_at_k
# ---------------------------------------------------------------------------


class TestPrecisionAtK:
    def test_all_relevant(self):
        retrieved = ["a", "b", "c", "d", "e"]
        relevant = {"a", "b", "c", "d", "e"}
        assert precision_at_k(retrieved, relevant, k=5) == pytest.approx(1.0)

    def test_none_relevant(self):
        retrieved = ["a", "b", "c"]
        relevant = {"x", "y"}
        assert precision_at_k(retrieved, relevant, k=3) == pytest.approx(0.0)

    def test_partial_relevant(self):
        retrieved = ["a", "b", "c", "d", "e"]
        relevant = {"a", "c"}
        # 2 hits in top-5 -> 2/5
        assert precision_at_k(retrieved, relevant, k=5) == pytest.approx(2 / 5)

    def test_k_zero_returns_zero(self):
        assert precision_at_k(["a", "b"], {"a"}, k=0) == 0.0

    def test_k_greater_than_retrieved(self):
        # Only 2 retrieved but k=5; denom is still k=5
        retrieved = ["a", "b"]
        relevant = {"a"}
        assert precision_at_k(retrieved, relevant, k=5) == pytest.approx(1 / 5)

    def test_empty_retrieved(self):
        assert precision_at_k([], {"a"}, k=5) == 0.0

    def test_k1_first_hit(self):
        assert precision_at_k(["a", "b"], {"a"}, k=1) == pytest.approx(1.0)

    def test_k1_no_hit(self):
        assert precision_at_k(["b", "a"], {"a"}, k=1) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# recall_at_k
# ---------------------------------------------------------------------------


class TestRecallAtK:
    def test_all_relevant_within_k(self):
        retrieved = ["a", "b"]
        relevant = {"a", "b"}
        assert recall_at_k(retrieved, relevant, k=5) == pytest.approx(1.0)

    def test_no_hits(self):
        assert recall_at_k(["c", "d"], {"a", "b"}, k=5) == pytest.approx(0.0)

    def test_partial(self):
        retrieved = ["a", "c", "d", "b", "e"]
        relevant = {"a", "b", "x"}  # 3 relevant, 2 in top-5
        assert recall_at_k(retrieved, relevant, k=5) == pytest.approx(2 / 3)

    def test_empty_relevant_returns_zero(self):
        assert recall_at_k(["a", "b"], set(), k=5) == 0.0

    def test_k_zero_returns_zero(self):
        assert recall_at_k(["a"], {"a"}, k=0) == 0.0


# ---------------------------------------------------------------------------
# reciprocal_rank
# ---------------------------------------------------------------------------


class TestReciprocalRank:
    def test_first_position(self):
        assert reciprocal_rank(["a", "b", "c"], {"a"}) == pytest.approx(1.0)

    def test_second_position(self):
        assert reciprocal_rank(["b", "a", "c"], {"a"}) == pytest.approx(0.5)

    def test_fifth_position(self):
        assert reciprocal_rank(["b", "c", "d", "e", "a"], {"a"}) == pytest.approx(0.2)

    def test_not_found(self):
        assert reciprocal_rank(["b", "c"], {"a"}) == 0.0

    def test_empty_retrieved(self):
        assert reciprocal_rank([], {"a"}) == 0.0

    def test_multiple_relevant_uses_first_hit(self):
        # Both "a" and "b" are relevant; "b" appears at rank 2
        assert reciprocal_rank(["c", "b", "a"], {"a", "b"}) == pytest.approx(1 / 2)


# ---------------------------------------------------------------------------
# ndcg_at_k
# ---------------------------------------------------------------------------


class TestNdcgAtK:
    def test_perfect_ranking(self):
        # Retrieved in optimal relevance order
        retrieved = ["a", "b", "c"]
        grades = {"a": 3.0, "b": 2.0, "c": 1.0}
        score = ndcg_at_k(retrieved, grades, k=3)
        assert score == pytest.approx(1.0, abs=1e-6)

    def test_no_relevant_returns_zero(self):
        retrieved = ["a", "b"]
        grades = {"a": 0.0, "b": 0.0}
        assert ndcg_at_k(retrieved, grades, k=5) == pytest.approx(0.0)

    def test_empty_retrieved_returns_zero(self):
        assert ndcg_at_k([], {"a": 3.0}, k=5) == 0.0

    def test_k_zero_returns_zero(self):
        assert ndcg_at_k(["a"], {"a": 2.0}, k=0) == 0.0

    def test_partial_relevance(self):
        # Retrieved: [irrelevant, relevant@grade2]
        retrieved = ["x", "a"]
        grades = {"a": 2.0}
        # IDCG = (2^2 - 1) / log2(2) = 3.0 / 1.0 = 3.0 at rank 1
        # DCG  = (2^0 - 1) / log2(2) + (2^2 - 1) / log2(3) = 0 + 3/log2(3)
        idcg = 3.0
        dcg = 3.0 / math.log2(3)
        expected = dcg / idcg
        assert ndcg_at_k(retrieved, grades, k=2) == pytest.approx(expected, rel=1e-5)

    def test_unknown_chunk_treated_as_zero_grade(self):
        retrieved = ["unknown", "a"]
        grades = {"a": 3.0}
        # IDCG at k=2 = grade 3.0 at rank 1 -> (2^3-1)/log2(2) = 7.0
        idcg = 7.0
        # DCG: rank1 unknown=grade0 -> 0; rank2 a=grade3 -> 7/log2(3)
        dcg = 7.0 / math.log2(3)
        assert ndcg_at_k(retrieved, grades, k=2) == pytest.approx(dcg / idcg, rel=1e-5)


# ---------------------------------------------------------------------------
# mean_reciprocal_rank & mean_metric
# ---------------------------------------------------------------------------


class TestAggregateMetrics:
    def test_mrr_single_query(self):
        assert mean_reciprocal_rank([0.5]) == pytest.approx(0.5)

    def test_mrr_multiple_queries(self):
        rrs = [1.0, 0.5, 0.25]
        expected = sum(rrs) / 3
        assert mean_reciprocal_rank(rrs) == pytest.approx(expected)

    def test_mrr_empty_list(self):
        assert mean_reciprocal_rank([]) == 0.0

    def test_mean_metric_standard(self):
        assert mean_metric([0.2, 0.4, 0.6]) == pytest.approx(0.4)

    def test_mean_metric_empty(self):
        assert mean_metric([]) == 0.0

    def test_mean_metric_single(self):
        assert mean_metric([0.75]) == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# intent_accuracy
# ---------------------------------------------------------------------------


class TestIntentAccuracy:
    def test_perfect_accuracy(self):
        pred = ["RETRIEVE", "FIX_BUG", "OPTIMIZE"]
        truth = ["RETRIEVE", "FIX_BUG", "OPTIMIZE"]
        assert intent_accuracy(pred, truth) == pytest.approx(1.0)

    def test_zero_accuracy(self):
        pred = ["ADD_FEATURE", "REFACTOR"]
        truth = ["RETRIEVE", "FIX_BUG"]
        assert intent_accuracy(pred, truth) == pytest.approx(0.0)

    def test_partial_accuracy(self):
        pred = ["RETRIEVE", "FIX_BUG", "OPTIMIZE"]
        truth = ["RETRIEVE", "OPTIMIZE", "OPTIMIZE"]
        # 2 correct: idx0 and idx2
        assert intent_accuracy(pred, truth) == pytest.approx(2 / 3)

    def test_none_prediction_counts_as_wrong(self):
        pred = [None, "RETRIEVE"]
        truth = ["RETRIEVE", "RETRIEVE"]
        assert intent_accuracy(pred, truth) == pytest.approx(0.5)

    def test_empty_lists_return_zero(self):
        assert intent_accuracy([], []) == 0.0

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError, match="Length mismatch"):
            intent_accuracy(["RETRIEVE"], ["RETRIEVE", "FIX_BUG"])


# ---------------------------------------------------------------------------
# per_class_intent_metrics
# ---------------------------------------------------------------------------


class TestPerClassIntentMetrics:
    def test_perfect_classification(self):
        pred = ["A", "B", "C"]
        truth = ["A", "B", "C"]
        metrics = per_class_intent_metrics(pred, truth)
        for cls in ["A", "B", "C"]:
            assert metrics[cls]["precision"] == pytest.approx(1.0)
            assert metrics[cls]["recall"] == pytest.approx(1.0)
            assert metrics[cls]["f1"] == pytest.approx(1.0)
            assert metrics[cls]["support"] == 1.0

    def test_confusion_impacts_per_class(self):
        # A predicted as B (fn for A, fp for B)
        pred = ["B", "B"]
        truth = ["A", "B"]
        metrics = per_class_intent_metrics(pred, truth)
        # Class A: tp=0, fp=0, fn=1 -> precision=0, recall=0, f1=0
        assert metrics["A"]["precision"] == 0.0
        assert metrics["A"]["recall"] == 0.0
        # Class B: tp=1, fp=1, fn=0 -> precision=0.5, recall=1.0, f1=2/3
        assert metrics["B"]["precision"] == pytest.approx(0.5)
        assert metrics["B"]["recall"] == pytest.approx(1.0)
        assert metrics["B"]["f1"] == pytest.approx(2 / 3)

    def test_explicit_labels_included(self):
        pred = ["A"]
        truth = ["A"]
        metrics = per_class_intent_metrics(pred, truth, labels=["A", "B", "C"])
        assert "B" in metrics
        assert "C" in metrics
        assert metrics["B"]["support"] == 0.0

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            per_class_intent_metrics(["A"], ["A", "B"])


# ---------------------------------------------------------------------------
# intent_confusion_matrix
# ---------------------------------------------------------------------------


class TestIntentConfusionMatrix:
    def test_perfect_diagonal(self):
        pred = ["A", "B", "C"]
        truth = ["A", "B", "C"]
        matrix = intent_confusion_matrix(pred, truth)
        assert matrix["A"]["A"] == 1
        assert matrix["B"]["B"] == 1
        assert matrix["C"]["C"] == 1
        # off-diagonal should be zero
        assert matrix["A"]["B"] == 0

    def test_off_diagonal_confusion(self):
        pred = ["B", "B"]
        truth = ["A", "B"]
        matrix = intent_confusion_matrix(pred, truth)
        # truth=A predicted=B -> matrix["A"]["B"] = 1
        assert matrix["A"]["B"] == 1
        assert matrix["B"]["B"] == 1
        assert matrix["A"]["A"] == 0

    def test_none_prediction_mapped_to_none_key(self):
        pred = [None]
        truth = ["RETRIEVE"]
        matrix = intent_confusion_matrix(pred, truth)
        assert matrix["RETRIEVE"]["__none__"] == 1

    def test_explicit_labels_included(self):
        pred = ["A"]
        truth = ["A"]
        matrix = intent_confusion_matrix(pred, truth, labels=["A", "B"])
        assert "B" in matrix
        assert matrix["B"]["B"] == 0

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            intent_confusion_matrix(["A"], ["A", "B"])


# ---------------------------------------------------------------------------
# Chunk matching and object-based metrics (file_path + symbol_name & fallbacks)
# ---------------------------------------------------------------------------


class TestChunkMatching:
    def test_match_by_chunk_id(self):
        retrieved = {"chunk_id": "c1", "file_path": "a.py"}
        expected = {"chunk_id": "c1", "file_path": "other.py"}
        assert is_chunk_match(retrieved, expected) is True

    def test_match_by_file_path_and_symbol_name(self):
        retrieved = {"file_path": "app/routers/appointment_routes.py", "symbol_name": "suggest_time"}
        expected = {"file_path": "app/routers/appointment_routes.py", "symbol_name": "suggest_time"}
        assert is_chunk_match(retrieved, expected) is True

    def test_symbol_name_mismatch_fails(self):
        retrieved = {"file_path": "app/routers/appointment_routes.py", "symbol_name": "doctor_is_available"}
        expected = {"file_path": "app/routers/appointment_routes.py", "symbol_name": "suggest_time"}
        assert is_chunk_match(retrieved, expected) is False

    def test_fallback_to_file_path_when_expected_has_no_symbol(self):
        retrieved = {"file_path": "app/config/settings.py", "symbol_name": "get_settings"}
        expected = {"file_path": "app/config/settings.py", "symbol_name": None}
        assert is_chunk_match(retrieved, expected) is True

    def test_fallback_to_file_path_when_retrieved_has_no_symbol(self):
        retrieved = {"file_path": "app/config/settings.py", "symbol_name": None}
        expected = {"file_path": "app/config/settings.py", "symbol_name": "get_settings"}
        assert is_chunk_match(retrieved, expected) is True

    def test_file_path_mismatch_fails(self):
        retrieved = {"file_path": "app/routers/patient_routes.py", "symbol_name": "suggest_time"}
        expected = {"file_path": "app/routers/appointment_routes.py", "symbol_name": "suggest_time"}
        assert is_chunk_match(retrieved, expected) is False

    def test_unmatched_chunk_returns_false(self):
        retrieved = {"file_path": "unrelated/file.py"}
        expected = {"file_path": "target/file.py", "symbol_name": "target_func"}
        assert is_chunk_match(retrieved, expected) is False

    def test_normalized_path_separators_match(self):
        retrieved = {"file_path": "app\\routers\\appointment_routes.py", "symbol_name": "suggest_time"}
        expected = {"file_path": "app/routers/appointment_routes.py", "symbol_name": "suggest_time"}
        assert is_chunk_match(retrieved, expected) is True


class TestMetricsWithChunkObjects:
    def test_precision_recall_with_file_and_symbol(self):
        retrieved = [
            {"file_path": "app/routers/appointment_routes.py", "symbol_name": "suggest_time"},
            {"file_path": "app/routers/patient_routes.py", "symbol_name": "create_patient"},
            {"file_path": "app/models/user.py", "symbol_name": "User"},
        ]
        expected = [
            {"file_path": "app/routers/appointment_routes.py", "symbol_name": "suggest_time", "relevance_grade": 2.0},
            {"file_path": "app/routers/doctor_routes.py", "symbol_name": "list_doctors", "relevance_grade": 1.0},
        ]
        # At k=3, 1 match out of 3 retrieved -> precision = 1/3
        assert precision_at_k(retrieved, expected, k=3) == pytest.approx(1 / 3)
        # 1 match out of 2 expected -> recall = 1/2
        assert recall_at_k(retrieved, expected, k=3) == pytest.approx(0.5)
        # First hit is at rank 1 -> RR = 1.0
        assert reciprocal_rank(retrieved, expected) == pytest.approx(1.0)

    def test_reciprocal_rank_unmatched_is_zero(self):
        retrieved = [
            {"file_path": "a.py", "symbol_name": "func_a"},
            {"file_path": "b.py", "symbol_name": "func_b"},
        ]
        expected = [
            {"file_path": "c.py", "symbol_name": "func_c"},
        ]
        assert precision_at_k(retrieved, expected, k=2) == 0.0
        assert recall_at_k(retrieved, expected, k=2) == 0.0
        assert reciprocal_rank(retrieved, expected) == 0.0

    def test_ndcg_with_file_and_symbol_grades(self):
        retrieved = [
            {"file_path": "app/routers/appointment_routes.py", "symbol_name": "suggest_time"},
            {"file_path": "app/routers/patient_routes.py", "symbol_name": "create_patient"},
        ]
        expected = [
            {"file_path": "app/routers/appointment_routes.py", "symbol_name": "suggest_time", "relevance_grade": 3.0},
            {"file_path": "app/routers/patient_routes.py", "symbol_name": "create_patient", "relevance_grade": 2.0},
        ]
        # Rank 1: grade 3, Rank 2: grade 2 -> optimal ranking -> ndcg = 1.0
        score = ndcg_at_k(retrieved, expected, k=2)
        assert score == pytest.approx(1.0)

