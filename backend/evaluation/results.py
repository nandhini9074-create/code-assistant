"""
evaluation/results.py
Result data schemas for Phase 2 retrieval and intent evaluation.

Provides typed containers for:
    - Per-query retrieval results (retrieved chunk IDs, ranks, scores)
    - Per-query retrieval metric scores
    - Aggregate retrieval evaluation report
    - Per-query intent classification results
    - Aggregate intent classification report
    - Combined evaluation report
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Retrieval evaluation results
# ---------------------------------------------------------------------------


class QueryRetrievalResult(BaseModel):
    """Holds per-query retrieval outcome and computed metric scores."""

    query_id: str = Field(..., description="Unique query identifier from the evaluation dataset.")
    query: str = Field(..., description="The query text.")
    collection_name: str = Field(..., description="Qdrant collection used for retrieval.")

    # Ground truth
    relevant_chunk_ids: List[str] = Field(
        default_factory=list,
        description="Ground-truth relevant chunk IDs for this query.",
    )
    relevance_grades: Dict[str, float] = Field(
        default_factory=dict,
        description="Chunk-id to numeric relevance grade mapping.",
    )

    # Retrieved outcome
    retrieved_chunk_ids: List[str] = Field(
        default_factory=list,
        description="Ordered list of retrieved chunk IDs (rank 1 first).",
    )
    retrieved_ranks: Dict[str, int] = Field(
        default_factory=dict,
        description="Chunk-id to 1-based rank mapping for retrieved chunks.",
    )

    # Per-query metric scores
    precision_at_k: float = Field(default=0.0, description="Precision@K.")
    recall_at_k: float = Field(default=0.0, description="Recall@K.")
    reciprocal_rank: float = Field(default=0.0, description="Reciprocal rank for this query.")
    ndcg_at_k: Optional[float] = Field(
        default=None,
        description="nDCG@K (None when no graded relevance labels are available).",
    )

    # Diagnostics
    error: Optional[str] = Field(default=None, description="Retrieval error message if any.")
    skipped: bool = Field(default=False, description="True if this query was skipped (e.g. no chunks).")


class RetrievalEvaluationReport(BaseModel):
    """Aggregate retrieval evaluation results across all queries in the dataset."""

    # Run metadata
    dataset_name: str = Field(default="")
    evaluated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    k: int = Field(default=5, description="Rank cut-off K used for all metrics.")
    total_queries: int = Field(default=0)
    evaluated_queries: int = Field(default=0)
    skipped_queries: int = Field(default=0)
    failed_queries: int = Field(default=0)

    # Aggregate scores
    mean_precision_at_k: float = Field(default=0.0, description="Mean Precision@K across all evaluated queries.")
    mean_recall_at_k: float = Field(default=0.0, description="Mean Recall@K across all evaluated queries.")
    mrr: float = Field(default=0.0, description="Mean Reciprocal Rank (MRR).")
    mean_ndcg_at_k: Optional[float] = Field(
        default=None,
        description="Mean nDCG@K (None when no queries had graded relevance labels).",
    )

    # Per-query breakdown
    per_query: List[QueryRetrievalResult] = Field(default_factory=list)

    def to_summary_dict(self) -> Dict[str, Any]:
        """Return a concise summary without per-query detail."""
        return {
            "dataset_name": self.dataset_name,
            "evaluated_at": self.evaluated_at,
            "k": self.k,
            "total_queries": self.total_queries,
            "evaluated_queries": self.evaluated_queries,
            "skipped_queries": self.skipped_queries,
            "failed_queries": self.failed_queries,
            "mean_precision_at_k": round(self.mean_precision_at_k, 4),
            "mean_recall_at_k": round(self.mean_recall_at_k, 4),
            "mrr": round(self.mrr, 4),
            "mean_ndcg_at_k": (
                round(self.mean_ndcg_at_k, 4) if self.mean_ndcg_at_k is not None else None
            ),
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize the full report to JSON."""
        return json.dumps(self.model_dump(mode="json"), indent=indent)


# ---------------------------------------------------------------------------
# Intent classification evaluation results
# ---------------------------------------------------------------------------


class QueryIntentResult(BaseModel):
    """Holds the per-query intent classification outcome."""

    query_id: str = Field(..., description="Unique query identifier.")
    query: str = Field(..., description="The query text.")
    expected_intent: str = Field(..., description="Ground-truth intent label.")
    predicted_intent: Optional[str] = Field(
        default=None,
        description="Predicted intent label (None if classification returned no result).",
    )
    correct: bool = Field(default=False, description="True if predicted == expected.")
    error: Optional[str] = Field(default=None, description="Error message if classification failed.")
    skipped: bool = Field(default=False, description="True if this query was skipped.")


class IntentEvaluationReport(BaseModel):
    """Aggregate intent classification evaluation results."""

    # Run metadata
    dataset_name: str = Field(default="")
    evaluated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    total_queries: int = Field(default=0)
    evaluated_queries: int = Field(default=0)
    skipped_queries: int = Field(default=0)
    failed_queries: int = Field(default=0)

    # Aggregate scores
    accuracy: float = Field(default=0.0, description="Overall intent classification accuracy.")

    # Per-class breakdown: {intent_label: {precision, recall, f1, support}}
    per_class_metrics: Dict[str, Dict[str, float]] = Field(default_factory=dict)

    # Confusion matrix: {true_label: {predicted_label: count}}
    confusion_matrix: Dict[str, Dict[str, int]] = Field(default_factory=dict)

    # Per-query breakdown
    per_query: List[QueryIntentResult] = Field(default_factory=list)

    def to_summary_dict(self) -> Dict[str, Any]:
        """Return a concise summary without per-query detail."""
        return {
            "dataset_name": self.dataset_name,
            "evaluated_at": self.evaluated_at,
            "total_queries": self.total_queries,
            "evaluated_queries": self.evaluated_queries,
            "skipped_queries": self.skipped_queries,
            "failed_queries": self.failed_queries,
            "accuracy": round(self.accuracy, 4),
            "per_class_metrics": {
                cls: {k: round(v, 4) for k, v in metrics.items()}
                for cls, metrics in self.per_class_metrics.items()
            },
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize the full report to JSON."""
        return json.dumps(self.model_dump(mode="json"), indent=indent)


# ---------------------------------------------------------------------------
# Combined evaluation report
# ---------------------------------------------------------------------------


class EvaluationReport(BaseModel):
    """Top-level evaluation report combining retrieval and intent evaluation results."""

    dataset_name: str = Field(default="")
    evaluated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    retrieval: Optional[RetrievalEvaluationReport] = Field(
        default=None,
        description="Retrieval evaluation results (None if not run).",
    )
    intent: Optional[IntentEvaluationReport] = Field(
        default=None,
        description="Intent classification evaluation results (None if not run).",
    )

    def to_summary_dict(self) -> Dict[str, Any]:
        """Return a compact summary of the combined evaluation."""
        return {
            "dataset_name": self.dataset_name,
            "evaluated_at": self.evaluated_at,
            "retrieval": self.retrieval.to_summary_dict() if self.retrieval else None,
            "intent": self.intent.to_summary_dict() if self.intent else None,
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize the full combined report to JSON."""
        return json.dumps(self.model_dump(mode="json"), indent=indent)
