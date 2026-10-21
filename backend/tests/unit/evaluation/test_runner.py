"""
tests/unit/evaluation/test_runner.py
Unit tests for evaluation/runner.py - EvaluationRunner.

Tests verify:
    - Intent-only evaluation (mock intent adapter)
    - Retrieval-only evaluation (mock retriever adapter)
    - Combined evaluation
    - Collection scoping enforcement (per-item vs default)
    - Skipping when no ground-truth chunks
    - Error propagation wrapped as AdapterError
    - Aggregate metric computation
    - Correct report structure
"""

from __future__ import annotations

from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.enums import IntentType
from app.modules.search.domain.search_domain import RetrievedChunk, SearchContext
from evaluation.adapters.base import BaseIntentAdapter, BaseRetrieverAdapter
from evaluation.exceptions import AdapterError
from evaluation.results import EvaluationReport, IntentEvaluationReport, RetrievalEvaluationReport
from evaluation.runner import EvaluationRunner
from evaluation.schemas import EvaluationDataset, EvaluationItem, RelevantChunk


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def make_item(
    query_id: str = "q1",
    query: str = "find authentication",
    intent: str = "RETRIEVE",
    collection: str = "test_coll",
    chunks: Optional[List[dict]] = None,
    repository: Optional[str] = None,
) -> EvaluationItem:
    if chunks is None:
        chunks = [{"chunk_id": "chunk_a", "relevance_grade": 2.0}]
    return EvaluationItem(
        query_id=query_id,
        query=query,
        expected_intent=IntentType(intent),
        collection_name=collection,
        repository=repository,
        expected_chunks=[RelevantChunk(**c) for c in chunks],
    )


def make_dataset(*items: EvaluationItem, name: str = "TestDataset") -> EvaluationDataset:
    return EvaluationDataset(dataset_name=name, items=list(items))


class FakeIntentAdapter(BaseIntentAdapter):
    """Deterministic intent adapter returning a fixed intent."""

    def __init__(self, fixed_intent: Optional[IntentType] = IntentType.RETRIEVE):
        self.fixed_intent = fixed_intent

    async def classify(self, query: str, repo_name: Optional[str] = None) -> Optional[IntentType]:
        return self.fixed_intent


class FakeRetrieverAdapter(BaseRetrieverAdapter):
    """Returns a fixed list of chunks for every call."""

    def __init__(self, chunks: List[RetrievedChunk]):
        self.chunks = chunks
        self.calls: List[dict] = []

    async def retrieve(
        self,
        query: str,
        collection_name: str,
        limit: int = 20,
        repo_name: Optional[str] = None,
    ) -> List[RetrievedChunk]:
        self.calls.append(
            {"query": query, "collection_name": collection_name, "limit": limit, "repo_name": repo_name}
        )
        return self.chunks


class FailingIntentAdapter(BaseIntentAdapter):
    """Always raises AdapterError."""

    async def classify(self, query: str, repo_name: Optional[str] = None) -> Optional[IntentType]:
        raise AdapterError("intent service down", adapter_name="FailingIntentAdapter")


class FailingRetrieverAdapter(BaseRetrieverAdapter):
    """Always raises AdapterError."""

    async def retrieve(self, query: str, collection_name: str, limit: int = 20, repo_name: Optional[str] = None):
        raise AdapterError("qdrant unreachable", adapter_name="FailingRetrieverAdapter")


# ---------------------------------------------------------------------------
# EvaluationRunner constructor
# ---------------------------------------------------------------------------


def test_runner_requires_at_least_one_adapter():
    with pytest.raises(ValueError, match="at least one"):
        EvaluationRunner()


def test_runner_with_intent_adapter_only():
    runner = EvaluationRunner(intent_adapter=FakeIntentAdapter())
    assert runner.intent_adapter is not None
    assert runner.retriever_adapter is None


def test_runner_with_retriever_adapter_only():
    runner = EvaluationRunner(retriever_adapter=FakeRetrieverAdapter([]))
    assert runner.retriever_adapter is not None
    assert runner.intent_adapter is None


# ---------------------------------------------------------------------------
# Intent-only evaluation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_intent_only_all_correct():
    """When the adapter always returns RETRIEVE and all items expect RETRIEVE, accuracy=1."""
    items = [
        make_item("q1", intent="RETRIEVE"),
        make_item("q2", intent="RETRIEVE"),
    ]
    dataset = make_dataset(*items)
    runner = EvaluationRunner(intent_adapter=FakeIntentAdapter(IntentType.RETRIEVE))
    report = await runner.run(dataset, k=5)

    assert isinstance(report, EvaluationReport)
    assert report.retrieval is None
    assert isinstance(report.intent, IntentEvaluationReport)
    assert report.intent.accuracy == pytest.approx(1.0)
    assert report.intent.total_queries == 2
    assert report.intent.evaluated_queries == 2
    assert len(report.intent.per_query) == 2
    assert all(r.correct for r in report.intent.per_query)


@pytest.mark.asyncio
async def test_intent_only_zero_accuracy():
    """When the adapter always returns FIX_BUG but items expect RETRIEVE, accuracy=0."""
    items = [make_item("q1", intent="RETRIEVE"), make_item("q2", intent="RETRIEVE")]
    dataset = make_dataset(*items)
    runner = EvaluationRunner(intent_adapter=FakeIntentAdapter(IntentType.FIX_BUG))
    report = await runner.run(dataset)

    assert report.intent.accuracy == pytest.approx(0.0)
    assert all(not r.correct for r in report.intent.per_query)


@pytest.mark.asyncio
async def test_intent_adapter_error_recorded_per_query():
    """AdapterError during intent classification is captured in the per-query result."""
    dataset = make_dataset(make_item("q1", intent="RETRIEVE"))
    runner = EvaluationRunner(intent_adapter=FailingIntentAdapter())
    report = await runner.run(dataset)

    assert report.intent.failed_queries == 1
    r = report.intent.per_query[0]
    assert r.error is not None
    assert "intent service down" in r.error
    assert r.correct is False


@pytest.mark.asyncio
async def test_intent_per_class_metrics_populated():
    """per_class_metrics in the intent report contains all evaluated intents."""
    items = [
        make_item("q1", intent="RETRIEVE"),
        make_item("q2", intent="FIX_BUG"),
    ]
    adapter = FakeIntentAdapter(IntentType.RETRIEVE)
    runner = EvaluationRunner(intent_adapter=adapter)
    report = await runner.run(make_dataset(*items))

    # Both labels should appear in per_class_metrics
    assert "RETRIEVE" in report.intent.per_class_metrics
    assert "FIX_BUG" in report.intent.per_class_metrics


@pytest.mark.asyncio
async def test_intent_confusion_matrix_populated():
    """The confusion matrix reflects actual prediction errors."""
    items = [
        make_item("q1", query="find auth", intent="RETRIEVE"),
        make_item("q2", query="fix the bug", intent="FIX_BUG"),
    ]
    # Always returns RETRIEVE -> q1 correct, q2 wrong
    runner = EvaluationRunner(intent_adapter=FakeIntentAdapter(IntentType.RETRIEVE))
    report = await runner.run(make_dataset(*items))

    cm = report.intent.confusion_matrix
    # true=FIX_BUG predicted=RETRIEVE should be 1
    assert cm["FIX_BUG"]["RETRIEVE"] == 1
    # true=RETRIEVE predicted=RETRIEVE should be 1
    assert cm["RETRIEVE"]["RETRIEVE"] == 1


# ---------------------------------------------------------------------------
# Retrieval-only evaluation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieval_only_perfect_hit():
    """When the first retrieved chunk matches the ground-truth, all metrics are 1."""
    expected_chunk_id = "chunk_a"
    fake_chunks = [
        RetrievedChunk(chunk_hash=expected_chunk_id, file_path="f.py", content="code", score=0.99)
    ]
    item = make_item("q1", chunks=[{"chunk_id": expected_chunk_id, "relevance_grade": 3.0}])
    dataset = make_dataset(item)

    runner = EvaluationRunner(retriever_adapter=FakeRetrieverAdapter(fake_chunks))
    report = await runner.run(dataset, k=5)

    assert report.intent is None
    assert isinstance(report.retrieval, RetrievalEvaluationReport)
    assert report.retrieval.mean_recall_at_k == pytest.approx(1.0)
    assert report.retrieval.mrr == pytest.approx(1.0)
    # nDCG should be 1.0 for a perfect single-result retrieval
    assert report.retrieval.mean_ndcg_at_k == pytest.approx(1.0, abs=1e-5)


@pytest.mark.asyncio
async def test_retrieval_only_no_hit():
    """When retrieved chunks don't match any ground-truth, all metrics are 0."""
    fake_chunks = [
        RetrievedChunk(chunk_hash="unrelated", file_path="f.py", content="code", score=0.5)
    ]
    item = make_item("q1", chunks=[{"chunk_id": "chunk_a", "relevance_grade": 2.0}])
    runner = EvaluationRunner(retriever_adapter=FakeRetrieverAdapter(fake_chunks))
    report = await runner.run(make_dataset(item), k=5)

    assert report.retrieval.mean_recall_at_k == pytest.approx(0.0)
    assert report.retrieval.mrr == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_retrieval_skips_item_without_collection():
    """Items without a collection_name and no default_collection are skipped."""
    item = EvaluationItem(
        query_id="q1",
        query="search something",
        expected_intent=IntentType.RETRIEVE,
        collection_name=None,
        expected_chunks=[RelevantChunk(chunk_id="chunk_a", relevance_grade=1.0)],
    )
    runner = EvaluationRunner(retriever_adapter=FakeRetrieverAdapter([]))
    report = await runner.run(make_dataset(item), k=5, default_collection=None)

    assert report.retrieval.skipped_queries == 1
    assert report.retrieval.evaluated_queries == 0


@pytest.mark.asyncio
async def test_retrieval_uses_default_collection_when_item_has_none():
    """Items without collection_name fall back to the default_collection argument."""
    item = EvaluationItem(
        query_id="q1",
        query="search something",
        expected_intent=IntentType.RETRIEVE,
        collection_name=None,
        expected_chunks=[RelevantChunk(chunk_id="chunk_a", relevance_grade=1.0)],
    )
    fake_adapter = FakeRetrieverAdapter(
        [RetrievedChunk(chunk_hash="chunk_a", file_path="f.py", content="c", score=0.9)]
    )
    runner = EvaluationRunner(retriever_adapter=fake_adapter)
    report = await runner.run(make_dataset(item), k=5, default_collection="default_coll")

    # Should not be skipped; collection resolved to "default_coll"
    assert report.retrieval.skipped_queries == 0
    assert fake_adapter.calls[0]["collection_name"] == "default_coll"


@pytest.mark.asyncio
async def test_retrieval_skips_item_without_expected_chunks():
    """Items with empty expected_chunks are skipped (no ground truth for retrieval)."""
    item = EvaluationItem(
        query_id="q1",
        query="search something",
        expected_intent=IntentType.RETRIEVE,
        collection_name="coll",
        expected_chunks=[],
    )
    runner = EvaluationRunner(retriever_adapter=FakeRetrieverAdapter([]))
    report = await runner.run(make_dataset(item), k=5)

    assert report.retrieval.skipped_queries == 1


@pytest.mark.asyncio
async def test_retrieval_adapter_error_recorded_per_query():
    """AdapterError from retriever is captured in the per-query result."""
    item = make_item("q1")
    runner = EvaluationRunner(retriever_adapter=FailingRetrieverAdapter())
    report = await runner.run(make_dataset(item), k=5)

    assert report.retrieval.failed_queries == 1
    r = report.retrieval.per_query[0]
    assert r.error is not None
    assert "qdrant unreachable" in r.error


@pytest.mark.asyncio
async def test_retrieval_uses_item_collection_not_default():
    """Item-level collection_name takes priority over default_collection."""
    item = make_item("q1", collection="item_collection")
    fake_adapter = FakeRetrieverAdapter(
        [RetrievedChunk(chunk_hash="chunk_a", file_path="f.py", content="c", score=0.9)]
    )
    runner = EvaluationRunner(retriever_adapter=fake_adapter)
    await runner.run(make_dataset(item), k=5, default_collection="fallback_collection")

    assert fake_adapter.calls[0]["collection_name"] == "item_collection"


@pytest.mark.asyncio
async def test_retrieval_aggregate_metrics_multiple_queries():
    """Aggregate metrics are computed correctly across multiple queries."""
    chunks_for_q1 = [RetrievedChunk(chunk_hash="a", file_path="f.py", content="c", score=0.9)]
    chunks_for_q2 = [RetrievedChunk(chunk_hash="x", file_path="g.py", content="c", score=0.5)]

    item1 = make_item("q1", chunks=[{"chunk_id": "a", "relevance_grade": 1.0}])
    item2 = make_item("q2", chunks=[{"chunk_id": "b", "relevance_grade": 1.0}])

    call_count = [0]

    class AlternatingRetriever(BaseRetrieverAdapter):
        async def retrieve(self, query, collection_name, limit=20, repo_name=None):
            call_count[0] += 1
            return chunks_for_q1 if call_count[0] == 1 else chunks_for_q2

    runner = EvaluationRunner(retriever_adapter=AlternatingRetriever())
    report = await runner.run(make_dataset(item1, item2), k=5)

    # q1: hit -> recall=1.0, rr=1.0; q2: no hit -> recall=0.0, rr=0.0
    assert report.retrieval.mean_recall_at_k == pytest.approx(0.5)
    assert report.retrieval.mrr == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Combined evaluation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_combined_evaluation_produces_both_reports():
    """Running with both adapters produces both retrieval and intent sub-reports."""
    fake_chunks = [RetrievedChunk(chunk_hash="chunk_a", file_path="f.py", content="c", score=0.9)]
    item = make_item("q1", intent="RETRIEVE")
    dataset = make_dataset(item)

    runner = EvaluationRunner(
        retriever_adapter=FakeRetrieverAdapter(fake_chunks),
        intent_adapter=FakeIntentAdapter(IntentType.RETRIEVE),
    )
    report = await runner.run(dataset, k=5)

    assert report.retrieval is not None
    assert report.intent is not None
    assert report.intent.accuracy == pytest.approx(1.0)
    assert report.retrieval.mrr == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Report structure / serialisation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_to_summary_dict():
    """EvaluationReport.to_summary_dict() returns a plain dict with expected keys."""
    item = make_item("q1")
    runner = EvaluationRunner(intent_adapter=FakeIntentAdapter())
    report = await runner.run(make_dataset(item))

    summary = report.to_summary_dict()
    assert "dataset_name" in summary
    assert "evaluated_at" in summary
    assert "retrieval" in summary  # may be None
    assert "intent" in summary


@pytest.mark.asyncio
async def test_report_to_json_is_valid_json():
    """EvaluationReport.to_json() produces valid JSON."""
    import json

    item = make_item("q1")
    runner = EvaluationRunner(intent_adapter=FakeIntentAdapter())
    report = await runner.run(make_dataset(item))
    parsed = json.loads(report.to_json())
    assert "dataset_name" in parsed


@pytest.mark.asyncio
async def test_per_query_ranks_recorded_correctly():
    """retrieved_ranks maps chunk_id -> 1-based rank in the QueryRetrievalResult."""
    fake_chunks = [
        RetrievedChunk(chunk_hash="x", file_path="f.py", content="c", score=0.9),
        RetrievedChunk(chunk_hash="chunk_a", file_path="g.py", content="c", score=0.7),
    ]
    item = make_item("q1", chunks=[{"chunk_id": "chunk_a", "relevance_grade": 1.0}])
    runner = EvaluationRunner(retriever_adapter=FakeRetrieverAdapter(fake_chunks))
    report = await runner.run(make_dataset(item), k=5)

    qr = report.retrieval.per_query[0]
    assert qr.retrieved_ranks["x"] == 1
    assert qr.retrieved_ranks["chunk_a"] == 2
    # chunk_a is at rank 2, so RR = 0.5
    assert qr.reciprocal_rank == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_runner_evaluates_item_without_chunk_id():
    """Verify runner handles expected chunks that only have file_path and symbol_name."""
    fake_chunks = [
        RetrievedChunk(
            chunk_hash="hash123",
            file_path="app/routers/appointment_routes.py",
            content="def suggest_time(): pass",
            score=0.95,
            metadata={"symbol_name": "suggest_time"},
        ),
        RetrievedChunk(
            chunk_hash="hash456",
            file_path="app/routers/other.py",
            content="def other(): pass",
            score=0.50,
        ),
    ]
    item = make_item(
        "q1",
        chunks=[
            {
                "file_path": "app/routers/appointment_routes.py",
                "symbol_name": "suggest_time",
                "relevance_grade": 3.0,
            }
        ],
    )
    runner = EvaluationRunner(retriever_adapter=FakeRetrieverAdapter(fake_chunks))
    report = await runner.run(make_dataset(item), k=5)

    assert report.retrieval is not None
    qr = report.retrieval.per_query[0]
    assert qr.precision_at_k == pytest.approx(1 / 5)
    assert qr.recall_at_k == pytest.approx(1.0)
    assert qr.reciprocal_rank == pytest.approx(1.0)
    assert qr.ndcg_at_k == pytest.approx(1.0)

