"""
evaluation/runner.py
Evaluation runner for Phase 2: orchestrates retrieval and intent classification
evaluation against an EvaluationDataset using the existing production adapters.

Usage (programmatic):
    runner = EvaluationRunner(
        retriever_adapter=ProductionRetrieverAdapter(code_retrieval_stage),
        intent_adapter=ProductionIntentAdapter(deterministic_only=True),
    )
    report = await runner.run(dataset, k=5)
    print(report.to_json())
"""

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional

from app.core.logging import get_logger
from evaluation.adapters.base import BaseIntentAdapter, BaseRetrieverAdapter
from evaluation.config import EvaluationConfig, get_evaluation_config
from evaluation.dataset import DatasetLoader
from evaluation.exceptions import AdapterError
from evaluation.metrics import (
    intent_accuracy,
    intent_confusion_matrix,
    mean_metric,
    mean_reciprocal_rank,
    ndcg_at_k,
    per_class_intent_metrics,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from evaluation.results import (
    EvaluationReport,
    IntentEvaluationReport,
    QueryIntentResult,
    QueryRetrievalResult,
    RetrievalEvaluationReport,
)
from evaluation.schemas import EvaluationDataset, EvaluationItem

logger = get_logger(__name__)


class EvaluationRunner:
    """
    Orchestrates retrieval and intent-classification evaluation against an
    EvaluationDataset.

    Pass ``retriever_adapter`` to enable retrieval evaluation.
    Pass ``intent_adapter`` to enable intent classification evaluation.
    At least one adapter must be provided.
    """

    def __init__(
        self,
        retriever_adapter: Optional[BaseRetrieverAdapter] = None,
        intent_adapter: Optional[BaseIntentAdapter] = None,
        config: Optional[EvaluationConfig] = None,
    ) -> None:
        if retriever_adapter is None and intent_adapter is None:
            raise ValueError(
                "EvaluationRunner requires at least one of retriever_adapter or intent_adapter."
            )
        self.retriever_adapter = retriever_adapter
        self.intent_adapter = intent_adapter
        self.config = config or get_evaluation_config()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        dataset: EvaluationDataset,
        k: int = 5,
        default_collection: Optional[str] = None,
    ) -> EvaluationReport:
        """
        Run the full evaluation (retrieval + intent) against the supplied dataset.

        Args:
            dataset:            The EvaluationDataset to evaluate.
            k:                  Rank cut-off for retrieval metrics (default 5).
            default_collection: Fallback Qdrant collection when the item does not
                                specify one.  Required when any item omits collection_name.

        Returns:
            EvaluationReport containing retrieval and/or intent sub-reports.
        """
        logger.info(
            "evaluation_run_started",
            dataset_name=dataset.dataset_name,
            total_items=len(dataset),
            k=k,
            run_retrieval=self.retriever_adapter is not None,
            run_intent=self.intent_adapter is not None,
        )

        retrieval_report: Optional[RetrievalEvaluationReport] = None
        intent_report: Optional[IntentEvaluationReport] = None

        if self.retriever_adapter is not None:
            retrieval_report = await self._run_retrieval_evaluation(
                dataset, k=k, default_collection=default_collection
            )

        if self.intent_adapter is not None:
            intent_report = await self._run_intent_evaluation(dataset)

        report = EvaluationReport(
            dataset_name=dataset.dataset_name,
            retrieval=retrieval_report,
            intent=intent_report,
        )

        logger.info(
            "evaluation_run_completed",
            dataset_name=dataset.dataset_name,
        )
        return report

    # ------------------------------------------------------------------
    # Retrieval evaluation
    # ------------------------------------------------------------------

    async def _run_retrieval_evaluation(
        self,
        dataset: EvaluationDataset,
        k: int,
        default_collection: Optional[str],
    ) -> RetrievalEvaluationReport:
        """Execute retrieval evaluation for every item in the dataset."""
        per_query_results: List[QueryRetrievalResult] = []
        skipped = 0
        failed = 0

        for item in dataset:
            result = await self._evaluate_retrieval_item(
                item=item, k=k, default_collection=default_collection
            )
            per_query_results.append(result)
            if result.skipped:
                skipped += 1
            elif result.error:
                failed += 1

        evaluated = len(per_query_results) - skipped - failed

        # Compute aggregates only over non-skipped, non-failed queries
        scored = [r for r in per_query_results if not r.skipped and not r.error]
        precision_vals = [r.precision_at_k for r in scored]
        recall_vals = [r.recall_at_k for r in scored]
        rr_vals = [r.reciprocal_rank for r in scored]
        ndcg_vals = [r.ndcg_at_k for r in scored if r.ndcg_at_k is not None]

        mean_ndcg: Optional[float] = mean_metric(ndcg_vals) if ndcg_vals else None

        report = RetrievalEvaluationReport(
            dataset_name=dataset.dataset_name,
            k=k,
            total_queries=len(dataset),
            evaluated_queries=evaluated,
            skipped_queries=skipped,
            failed_queries=failed,
            mean_precision_at_k=mean_metric(precision_vals),
            mean_recall_at_k=mean_metric(recall_vals),
            mrr=mean_reciprocal_rank(rr_vals),
            mean_ndcg_at_k=mean_ndcg,
            per_query=per_query_results,
        )

        logger.info(
            "retrieval_evaluation_completed",
            dataset_name=dataset.dataset_name,
            k=k,
            mean_precision=round(report.mean_precision_at_k, 4),
            mean_recall=round(report.mean_recall_at_k, 4),
            mrr=round(report.mrr, 4),
            mean_ndcg=round(mean_ndcg, 4) if mean_ndcg is not None else None,
        )
        return report

    async def _evaluate_retrieval_item(
        self,
        item: EvaluationItem,
        k: int,
        default_collection: Optional[str],
    ) -> QueryRetrievalResult:
        """Evaluate retrieval for a single EvaluationItem."""
        # Resolve collection
        collection_name = item.collection_name or default_collection
        if not collection_name:
            logger.warning(
                "retrieval_item_skipped_no_collection",
                query_id=item.query_id,
            )
            return QueryRetrievalResult(
                query_id=item.query_id,
                query=item.query,
                collection_name="",
                relevant_chunk_ids=[c.identifier for c in item.expected_chunks],
                skipped=True,
            )

        # Build ground-truth sets and identifiers
        relevant_identifiers = [c.identifier for c in item.expected_chunks]
        relevance_grades: Dict[str, float] = {
            c.identifier: c.relevance_grade for c in item.expected_chunks
        }

        # Skip if no ground-truth chunks exist (retrieval evaluation not possible)
        if not item.expected_chunks:
            logger.warning(
                "retrieval_item_skipped_no_expected_chunks",
                query_id=item.query_id,
            )
            return QueryRetrievalResult(
                query_id=item.query_id,
                query=item.query,
                collection_name=collection_name,
                relevant_chunk_ids=[],
                skipped=True,
            )

        # Call retriever
        try:
            chunks = await self.retriever_adapter.retrieve(  # type: ignore[union-attr]
                query=item.query,
                collection_name=collection_name,
                limit=max(k, self.config.default_retrieval_limit),
                repo_name=item.repository,
            )
        except AdapterError as exc:
            logger.error(
                "retrieval_adapter_error",
                query_id=item.query_id,
                error=str(exc),
            )
            return QueryRetrievalResult(
                query_id=item.query_id,
                query=item.query,
                collection_name=collection_name,
                relevant_chunk_ids=relevant_identifiers,
                relevance_grades=relevance_grades,
                error=str(exc),
            )

        retrieved_ids = [
            getattr(c, "chunk_hash", None)
            or getattr(c, "chunk_id", None)
            or getattr(c, "file_path", None)
            or str(c)
            for c in chunks
        ]
        retrieved_ranks = {cid: rank for rank, cid in enumerate(retrieved_ids, start=1)}

        # Compute per-query metrics using full chunk objects and expected chunks
        p_at_k = precision_at_k(chunks, item.expected_chunks, k)
        r_at_k = recall_at_k(chunks, item.expected_chunks, k)
        rr = reciprocal_rank(chunks, item.expected_chunks)

        # nDCG only when graded labels are available (any grade != 1.0 or explicitly set)
        has_graded = any(v != 1.0 for v in relevance_grades.values()) or bool(relevance_grades)
        ndcg: Optional[float] = ndcg_at_k(chunks, item.expected_chunks, k) if has_graded else None

        return QueryRetrievalResult(
            query_id=item.query_id,
            query=item.query,
            collection_name=collection_name,
            relevant_chunk_ids=relevant_identifiers,
            relevance_grades=relevance_grades,
            retrieved_chunk_ids=retrieved_ids,
            retrieved_ranks=retrieved_ranks,
            precision_at_k=p_at_k,
            recall_at_k=r_at_k,
            reciprocal_rank=rr,
            ndcg_at_k=ndcg,
        )

    # ------------------------------------------------------------------
    # Intent classification evaluation
    # ------------------------------------------------------------------

    async def _run_intent_evaluation(
        self,
        dataset: EvaluationDataset,
    ) -> IntentEvaluationReport:
        """Execute intent classification evaluation for every item in the dataset."""
        per_query_results: List[QueryIntentResult] = []
        skipped = 0
        failed = 0

        for item in dataset:
            result = await self._evaluate_intent_item(item)
            per_query_results.append(result)
            if result.skipped:
                skipped += 1
            elif result.error:
                failed += 1

        evaluated = len(per_query_results) - skipped - failed

        # Compute aggregate metrics from non-skipped, non-failed queries
        scored = [r for r in per_query_results if not r.skipped and not r.error]
        predicted_labels = [r.predicted_intent for r in scored]
        ground_truth_labels = [r.expected_intent for r in scored]

        accuracy = intent_accuracy(predicted_labels, ground_truth_labels) if scored else 0.0
        per_class = (
            per_class_intent_metrics(predicted_labels, ground_truth_labels)
            if scored
            else {}
        )
        confusion = (
            intent_confusion_matrix(predicted_labels, ground_truth_labels)
            if scored
            else {}
        )

        report = IntentEvaluationReport(
            dataset_name=dataset.dataset_name,
            total_queries=len(dataset),
            evaluated_queries=evaluated,
            skipped_queries=skipped,
            failed_queries=failed,
            accuracy=accuracy,
            per_class_metrics=per_class,
            confusion_matrix=confusion,
            per_query=per_query_results,
        )

        logger.info(
            "intent_evaluation_completed",
            dataset_name=dataset.dataset_name,
            accuracy=round(accuracy, 4),
            evaluated=evaluated,
        )
        return report

    async def _evaluate_intent_item(self, item: EvaluationItem) -> QueryIntentResult:
        """Classify the intent of a single EvaluationItem and compare to ground truth."""
        expected = item.expected_intent.value

        try:
            predicted_intent = await self.intent_adapter.classify(  # type: ignore[union-attr]
                query=item.query,
                repo_name=item.repository,
            )
            predicted = predicted_intent.value if predicted_intent is not None else None
        except AdapterError as exc:
            logger.error(
                "intent_adapter_error",
                query_id=item.query_id,
                error=str(exc),
            )
            return QueryIntentResult(
                query_id=item.query_id,
                query=item.query,
                expected_intent=expected,
                predicted_intent=None,
                correct=False,
                error=str(exc),
            )

        correct = predicted == expected
        return QueryIntentResult(
            query_id=item.query_id,
            query=item.query,
            expected_intent=expected,
            predicted_intent=predicted,
            correct=correct,
        )
