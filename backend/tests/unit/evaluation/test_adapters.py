"""
tests/unit/evaluation/test_adapters.py
Unit tests for evaluation adapter interfaces wrapping production search components.
"""

from unittest.mock import AsyncMock, MagicMock
import pytest

from app.core.enums import IntentType
from app.modules.search.domain.search_domain import RetrievedChunk, SearchContext
from evaluation.adapters.intent_adapter import ProductionIntentAdapter
from evaluation.adapters.retriever_adapter import ProductionRetrieverAdapter
from evaluation.exceptions import AdapterError


@pytest.mark.asyncio
async def test_intent_adapter_deterministic_classification_all_intents():
    """Verify ProductionIntentAdapter in deterministic mode correctly identifies all 6 intents using production rules."""
    adapter = ProductionIntentAdapter(deterministic_only=True)

    # 1. RETRIEVE
    res_retrieve = await adapter.classify("where is the authentication middleware located?")
    assert res_retrieve == IntentType.RETRIEVE

    # 2. ADD_FEATURE
    res_feature = await adapter.classify("add a new rate limiting interceptor")
    assert res_feature == IntentType.ADD_FEATURE

    # 3. FIX_BUG
    res_bug = await adapter.classify("fix broken json parsing in webhook payload")
    assert res_bug == IntentType.FIX_BUG

    # 6. FIX_VULNERABILITY
    res_vuln = await adapter.classify("fix the security vulnerability in package dependencies")
    assert res_vuln == IntentType.FIX_VULNERABILITY


@pytest.mark.asyncio
async def test_intent_adapter_empty_query():
    """Verify ProductionIntentAdapter returns None for empty queries."""
    adapter = ProductionIntentAdapter()
    assert await adapter.classify("") is None
    assert await adapter.classify("   ") is None


@pytest.mark.asyncio
async def test_intent_adapter_with_mock_stage():
    """Verify ProductionIntentAdapter delegates to IntentClassificationStage when provided."""
    mock_stage = AsyncMock()

    async def fake_execute(context: SearchContext):
        context.intent = IntentType.ADD_FEATURE

    mock_stage.execute.side_effect = fake_execute

    adapter = ProductionIntentAdapter(stage=mock_stage)
    result = await adapter.classify("implement caching")

    assert result == IntentType.ADD_FEATURE
    mock_stage.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_intent_adapter_stage_error_fallback():
    """Verify ProductionIntentAdapter gracefully falls back to deterministic rules if stage fails."""
    mock_stage = AsyncMock()
    mock_stage.execute.side_effect = RuntimeError("LLM service unavailable")

    adapter = ProductionIntentAdapter(stage=mock_stage)
    # Even if stage raises, fallback handles known keywords
    result = await adapter.classify("fix the memory leak error")

    assert result == IntentType.FIX_BUG


@pytest.mark.asyncio
async def test_retriever_adapter_success():
    """Verify ProductionRetrieverAdapter delegates to CodeRetrievalStage and extracts retrieved_chunks."""
    mock_stage = AsyncMock()

    async def fake_execute(context: SearchContext, limit: int = 20):
        context.retrieved_chunks = [
            RetrievedChunk(
                chunk_hash="chunk_test_123",
                file_path="src/main.py",
                content="def app(): pass",
                score=0.95,
            )
        ]

    mock_stage.execute.side_effect = fake_execute

    adapter = ProductionRetrieverAdapter(stage=mock_stage)
    chunks = await adapter.retrieve(
        query="show main app",
        collection_name="repo_collection",
        limit=10,
    )

    assert len(chunks) == 1
    assert chunks[0].chunk_hash == "chunk_test_123"
    assert chunks[0].file_path == "src/main.py"
    assert chunks[0].score == 0.95


@pytest.mark.asyncio
async def test_retriever_adapter_empty_query():
    """Verify ProductionRetrieverAdapter returns empty list for empty query."""
    mock_stage = AsyncMock()
    adapter = ProductionRetrieverAdapter(stage=mock_stage)
    result = await adapter.retrieve(query="   ", collection_name="coll")
    assert result == []
    mock_stage.execute.assert_not_called()


@pytest.mark.asyncio
async def test_retriever_adapter_error_raises_adapter_error():
    """Verify ProductionRetrieverAdapter wraps unexpected stage exceptions into AdapterError."""
    mock_stage = AsyncMock()
    mock_stage.execute.side_effect = RuntimeError("Qdrant connection refused")

    adapter = ProductionRetrieverAdapter(stage=mock_stage)
    with pytest.raises(AdapterError) as exc_info:
        await adapter.retrieve(query="find something", collection_name="test_coll")

    assert "Qdrant connection refused" in str(exc_info.value)
    assert exc_info.value.adapter_name == "ProductionRetrieverAdapter"
