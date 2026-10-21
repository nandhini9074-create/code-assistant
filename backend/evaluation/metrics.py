"""
evaluation/metrics.py
Retrieval and intent-classification evaluation metrics for the RepoLens Evaluation Framework.

Retrieval metrics (all computed at rank cut-off K):
    - Precision@K
    - Recall@K
    - Mean Reciprocal Rank (MRR)
    - Normalised Discounted Cumulative Gain (nDCG@K)

Intent-classification metrics:
    - Overall accuracy
    - Per-class precision, recall, F1
    - Confusion matrix (dict-of-dict representation)
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Set, Union


# ---------------------------------------------------------------------------
# Path & Chunk Matching Helpers
# ---------------------------------------------------------------------------


def normalize_path(path: Optional[str]) -> str:
    """Normalize file paths for cross-platform and relative matching."""
    if not path or not isinstance(path, str):
        return ""
    p = path.strip().replace("\\", "/").lower()
    while p.startswith("./"):
        p = p[2:]
    return p.lstrip("/")


def paths_match(path1: Optional[str], path2: Optional[str]) -> bool:
    """
    Check if two file paths refer to the same file.
    Supports relative path suffixes (e.g. 'app/routers/appointments.py'
    matching 'backend/app/routers/appointments.py').
    """
    n1 = normalize_path(path1)
    n2 = normalize_path(path2)
    if not n1 or not n2:
        return False
    if n1 == n2:
        return True
    if n1.endswith("/" + n2) or n2.endswith("/" + n1):
        return True
    return False


def extract_chunk_info(chunk: Any) -> Dict[str, Optional[str]]:
    """Extract (chunk_id, file_path, symbol_name) from string, dict, or object."""
    if chunk is None:
        return {"chunk_id": None, "file_path": None, "symbol_name": None}

    if isinstance(chunk, str):
        # Support composite identifiers like "path/to/file.py::symbol_name"
        if "::" in chunk:
            fp, sym = chunk.split("::", 1)
            return {"chunk_id": chunk, "file_path": fp.strip(), "symbol_name": sym.strip()}
        return {"chunk_id": chunk, "file_path": None, "symbol_name": None}

    if isinstance(chunk, dict):
        cid = chunk.get("chunk_id") or chunk.get("chunk_hash")
        fp = chunk.get("file_path")
        meta = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
        sym = (
            chunk.get("symbol_name")
            or meta.get("symbol_name")
            or meta.get("name")
            or meta.get("function_name")
            or meta.get("class_name")
        )
        return {
            "chunk_id": str(cid) if cid else None,
            "file_path": str(fp) if fp else None,
            "symbol_name": str(sym) if sym else None,
        }

    # Python object (RetrievedChunk, RelevantChunk, or mock)
    cid = getattr(chunk, "chunk_id", None) or getattr(chunk, "chunk_hash", None)
    fp = getattr(chunk, "file_path", None)
    meta = getattr(chunk, "metadata", {}) or {}
    sym = (
        getattr(chunk, "symbol_name", None)
        or meta.get("symbol_name")
        or meta.get("name")
        or meta.get("function_name")
        or meta.get("class_name")
    )
    return {
        "chunk_id": str(cid) if cid else None,
        "file_path": str(fp) if fp else None,
        "symbol_name": str(sym) if sym else None,
    }


def is_chunk_match(retrieved: Any, expected: Any) -> bool:
    """
    Determine whether a retrieved chunk matches an expected chunk.

    Rules:
    1. If expected specifies chunk_id and both have chunk_id: match if IDs are equal.
    2. If file_path is available on both:
       - If symbol_name is available on both: match if symbols match (case-insensitive).
       - If symbol_name is unavailable on either: fallback to file_path match.
    3. Otherwise: no match.
    """
    r_info = extract_chunk_info(retrieved)
    e_info = extract_chunk_info(expected)

    r_id = r_info["chunk_id"]
    e_id = e_info["chunk_id"]
    r_fp = r_info["file_path"]
    e_fp = e_info["file_path"]
    r_sym = r_info["symbol_name"]
    e_sym = e_info["symbol_name"]

    # Direct ID match
    if e_id and r_id and e_id == r_id:
        return True

    # File path + symbol_name match
    if e_fp and r_fp and paths_match(r_fp, e_fp):
        # Both specify symbol_name -> require symbol match
        if e_sym and r_sym:
            return e_sym.strip().lower() == r_sym.strip().lower()
        # symbol_name unavailable on either -> fallback to file_path match
        return True

    return False


def get_chunk_grade(
    retrieved_chunk: Any,
    relevance_grades: Union[Dict[Any, float], Sequence[Any]],
) -> float:
    """Find the highest relevance grade for a retrieved chunk among expected items."""
    best_grade = 0.0

    if isinstance(relevance_grades, dict):
        r_info = extract_chunk_info(retrieved_chunk)
        r_id = r_info["chunk_id"]
        if r_id and r_id in relevance_grades:
            return float(relevance_grades[r_id])

        for key_item, grade in relevance_grades.items():
            if is_chunk_match(retrieved_chunk, key_item):
                best_grade = max(best_grade, float(grade))

    elif isinstance(relevance_grades, (list, tuple, set)):
        for item in relevance_grades:
            grade = getattr(item, "relevance_grade", None)
            if grade is None and isinstance(item, dict):
                grade = item.get("relevance_grade")
            if grade is not None and is_chunk_match(retrieved_chunk, item):
                best_grade = max(best_grade, float(grade))

    return best_grade


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _ideal_dcg(grades: Sequence[float], k: int) -> float:
    """Compute the Ideal DCG (IDCG) for the top-k positions."""
    sorted_grades = sorted(grades, reverse=True)[:k]
    return sum(
        (2.0 ** g - 1.0) / math.log2(rank + 2)
        for rank, g in enumerate(sorted_grades)
    )


# ---------------------------------------------------------------------------
# Per-query retrieval metrics
# ---------------------------------------------------------------------------


def precision_at_k(
    retrieved_ids: Sequence[Any],
    relevant_ids: Union[Sequence[Any], Set[Any]],
    k: int,
) -> float:
    """
    Compute Precision@K.

    Args:
        retrieved_ids: Ordered list of retrieved chunk IDs or chunk objects (rank 1 first).
        relevant_ids:  Set or list of ground-truth relevant chunk IDs or RelevantChunk objects.
        k:             Rank cut-off.

    Returns:
        Precision@K in [0.0, 1.0].
    """
    if k <= 0:
        return 0.0
    top_k = retrieved_ids[:k]
    if not top_k:
        return 0.0

    hits = sum(1 for r in top_k if any(is_chunk_match(r, e) for e in relevant_ids))
    return hits / k


def recall_at_k(
    retrieved_ids: Sequence[Any],
    relevant_ids: Union[Sequence[Any], Set[Any]],
    k: int,
) -> float:
    """
    Compute Recall@K.

    Args:
        retrieved_ids: Ordered list of retrieved chunk IDs or chunk objects (rank 1 first).
        relevant_ids:  Set or list of ground-truth relevant chunk IDs or RelevantChunk objects.
        k:             Rank cut-off.

    Returns:
        Recall@K in [0.0, 1.0]. Returns 0.0 when relevant_ids is empty.
    """
    if not relevant_ids or k <= 0:
        return 0.0
    top_k = retrieved_ids[:k]
    if not top_k:
        return 0.0

    matched_expected = sum(
        1 for e in relevant_ids if any(is_chunk_match(r, e) for r in top_k)
    )
    return matched_expected / len(relevant_ids)


def reciprocal_rank(
    retrieved_ids: Sequence[Any],
    relevant_ids: Union[Sequence[Any], Set[Any]],
) -> float:
    """
    Compute Reciprocal Rank (RR) for a single query.

    Args:
        retrieved_ids: Ordered list of retrieved chunk IDs or chunk objects (rank 1 first).
        relevant_ids:  Set or list of ground-truth relevant chunk IDs or RelevantChunk objects.

    Returns:
        1 / rank_of_first_hit, or 0.0 if no relevant chunk is found.
    """
    for rank, r in enumerate(retrieved_ids, start=1):
        if any(is_chunk_match(r, e) for e in relevant_ids):
            return 1.0 / rank
    return 0.0


def ndcg_at_k(
    retrieved_ids: Sequence[Any],
    relevance_grades: Union[Dict[Any, float], Sequence[Any]],
    k: int,
) -> float:
    """
    Compute nDCG@K using graded relevance labels.

    Args:
        retrieved_ids:    Ordered list of retrieved chunk IDs or chunk objects (rank 1 first).
        relevance_grades: Mapping from chunk_id -> numeric grade, or list of RelevantChunk objects.
        k:                Rank cut-off.

    Returns:
        nDCG@K in [0.0, 1.0]. Returns 0.0 when all grades are 0 or result list is empty.
    """
    if k <= 0 or not retrieved_ids:
        return 0.0

    if isinstance(relevance_grades, dict):
        all_grades = [float(v) for v in relevance_grades.values()]
    elif isinstance(relevance_grades, (list, tuple, set)):
        all_grades = [
            float(getattr(item, "relevance_grade", item.get("relevance_grade", 0.0) if isinstance(item, dict) else 0.0))
            for item in relevance_grades
        ]
    else:
        all_grades = []

    idcg = _ideal_dcg(all_grades, k)
    if idcg == 0.0:
        return 0.0

    dcg = sum(
        (2.0 ** get_chunk_grade(r, relevance_grades) - 1.0) / math.log2(rank + 2)
        for rank, r in enumerate(retrieved_ids[:k])
    )
    return dcg / idcg


# ---------------------------------------------------------------------------
# Aggregate retrieval metrics
# ---------------------------------------------------------------------------


def mean_reciprocal_rank(per_query_rr: List[float]) -> float:
    """
    Compute Mean Reciprocal Rank (MRR) across a list of per-query RR values.

    Args:
        per_query_rr: List of reciprocal rank values (one per query).

    Returns:
        MRR in [0.0, 1.0].  Returns 0.0 for an empty list.
    """
    if not per_query_rr:
        return 0.0
    return sum(per_query_rr) / len(per_query_rr)


def mean_metric(values: List[float]) -> float:
    """
    Compute the arithmetic mean of a list of float values.

    Args:
        values: List of per-query metric values.

    Returns:
        Mean value, or 0.0 for an empty list.
    """
    if not values:
        return 0.0
    return sum(values) / len(values)


# ---------------------------------------------------------------------------
# Intent classification metrics
# ---------------------------------------------------------------------------


def intent_accuracy(predicted: List[Optional[str]], ground_truth: List[str]) -> float:
    """
    Compute overall accuracy for intent classification.

    Args:
        predicted:    List of predicted intent strings (None counts as wrong).
        ground_truth: List of ground-truth intent strings (same length as predicted).

    Returns:
        Accuracy in [0.0, 1.0].  Returns 0.0 for empty lists.

    Raises:
        ValueError: If the lists have different lengths.
    """
    if len(predicted) != len(ground_truth):
        raise ValueError(
            f"Length mismatch: predicted has {len(predicted)} items, "
            f"ground_truth has {len(ground_truth)} items."
        )
    if not ground_truth:
        return 0.0
    correct = sum(p == g for p, g in zip(predicted, ground_truth))
    return correct / len(ground_truth)


def per_class_intent_metrics(
    predicted: List[Optional[str]],
    ground_truth: List[str],
    labels: Optional[List[str]] = None,
) -> Dict[str, Dict[str, float]]:
    """
    Compute per-class precision, recall, and F1 for intent classification.

    Args:
        predicted:    List of predicted intent strings (None counts as wrong).
        ground_truth: List of ground-truth intent strings.
        labels:       Optional explicit list of class labels to include.
                      Defaults to the union of all values in ground_truth and predicted.

    Returns:
        Dict mapping each class label to a dict with keys:
            - "precision": float in [0.0, 1.0]
            - "recall":    float in [0.0, 1.0]
            - "f1":        float in [0.0, 1.0]
            - "support":   int (number of ground-truth instances for this class)

    Raises:
        ValueError: If the lists have different lengths.
    """
    if len(predicted) != len(ground_truth):
        raise ValueError(
            f"Length mismatch: predicted has {len(predicted)} items, "
            f"ground_truth has {len(ground_truth)} items."
        )

    # Determine all classes to score
    all_classes: Set[str] = set(ground_truth)
    if labels is not None:
        all_classes.update(labels)
    else:
        all_classes.update(p for p in predicted if p is not None)

    result: Dict[str, Dict[str, float]] = {}
    for cls in sorted(all_classes):
        tp = sum(1 for p, g in zip(predicted, ground_truth) if p == cls and g == cls)
        fp = sum(1 for p, g in zip(predicted, ground_truth) if p == cls and g != cls)
        fn = sum(1 for p, g in zip(predicted, ground_truth) if p != cls and g == cls)
        support = tp + fn

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (
            2.0 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )

        result[cls] = {
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1": round(f1, 6),
            "support": float(support),
        }

    return result


def intent_confusion_matrix(
    predicted: List[Optional[str]],
    ground_truth: List[str],
    labels: Optional[List[str]] = None,
) -> Dict[str, Dict[str, int]]:
    """
    Build a confusion matrix for intent classification.

    The matrix is indexed as confusion[true_label][predicted_label] = count.
    None predictions are represented as the string "__none__".

    Args:
        predicted:    List of predicted intent strings (None allowed).
        ground_truth: List of ground-truth intent strings.
        labels:       Optional explicit list of class labels (row/column headers).

    Returns:
        Dict-of-dict confusion matrix where
            confusion[true_label][predicted_label] = count

    Raises:
        ValueError: If the lists have different lengths.
    """
    if len(predicted) != len(ground_truth):
        raise ValueError(
            f"Length mismatch: predicted has {len(predicted)} items, "
            f"ground_truth has {len(ground_truth)} items."
        )

    # Normalize None predictions
    pred_normalized = [p if p is not None else "__none__" for p in predicted]

    all_true: Set[str] = set(ground_truth)
    all_pred: Set[str] = set(pred_normalized)
    if labels:
        all_true.update(labels)
        all_pred.update(labels)

    all_labels = sorted(all_true | all_pred)

    # Initialise matrix with zeros
    matrix: Dict[str, Dict[str, int]] = {
        true_lbl: {pred_lbl: 0 for pred_lbl in all_labels}
        for true_lbl in all_labels
    }

    for pred_lbl, true_lbl in zip(pred_normalized, ground_truth):
        if true_lbl in matrix and pred_lbl in matrix[true_lbl]:
            matrix[true_lbl][pred_lbl] += 1

    return matrix
