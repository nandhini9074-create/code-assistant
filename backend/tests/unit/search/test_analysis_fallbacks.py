"""Tests for deterministic search-flow fallback behavior."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.enums import IntentType
from app.modules.search.domain.search_domain import RetrievedChunk, SearchContext
from app.modules.search.pipeline.code_analysis import CodeAnalysisStage
from app.modules.search.pipeline.final_triage import FinalTriageStage
from app.modules.search.pipeline.response_generation import ResponseGenerationStage


QUERY = "Fix the bug in suggest_time where valid appointment times are rejected"


def make_context() -> SearchContext:
    chunk = RetrievedChunk(
        chunk_hash="chunk-1",
        file_path="app/routers/appointments.py",
        content="def suggest_time(payload):\n    return available",
        score=0.91,
        metadata={
            "function_name": "suggest_time",
            "start_line": 239,
            "end_line": 287,
        },
    )
    return SearchContext(
        query=QUERY,
        repo_name="hospital_management",
        repo_owner="ashwathie",
        intent=IntentType.FIX_BUG,
        retrieved_chunks=[chunk],
        primary_chunk=chunk,
        target_symbol="suggest_time",
        llm_context="def suggest_time(payload):\n    return available",
    )


@pytest.mark.asyncio
async def test_analysis_failure_continues_with_conservative_fallback():
    context = make_context()
    service = SimpleNamespace(
        analyze=AsyncMock(side_effect=TimeoutError("provider timeout"))
    )

    await CodeAnalysisStage(service).execute(context)
    context.validation_status = "unavailable"
    await FinalTriageStage().execute(context)
    await ResponseGenerationStage().execute(context)

    response = context.final_response.model_dump()
    assert "failed" not in str(response).lower()
    assert "suggest_time" in response["suggestion"]
    assert "safe exact code change" in response["suggestion"]
    assert response["suggested_code"] is None
    assert response["confidence"] == "medium"


@pytest.mark.asyncio
async def test_suggestion_failure_preserves_safe_fallback():
    context = make_context()
    service = SimpleNamespace(
        analyze=AsyncMock(
            return_value={
                "error": "Code suggestion failed: invalid JSON",
                "current_behavior": "The target behavior is unclear.",
            }
        )
    )

    await CodeAnalysisStage(service).execute(context)
    context.validation_status = "unavailable"
    await FinalTriageStage().execute(context)
    await ResponseGenerationStage().execute(context)

    response = context.final_response.model_dump()
    assert "Code suggestion failed" not in str(response)
    assert "suggest_time" in response["suggestion"]
    assert response["suggested_code"] is None
    assert response["confidence"] == "medium"


@pytest.mark.asyncio
async def test_insufficient_evidence_is_low_confidence_without_patch():
    context = make_context()
    context.retrieved_chunks = []
    context.primary_chunk = None
    context.target_symbol = None
    context.llm_context = ""
    service = SimpleNamespace(
        analyze=AsyncMock(side_effect=ValueError("invalid JSON"))
    )

    await CodeAnalysisStage(service).execute(context)
    context.validation_status = "unavailable"
    await FinalTriageStage().execute(context)
    await ResponseGenerationStage().execute(context)

    response = context.final_response.model_dump()
    assert response["suggested_code"] is None
    assert response["confidence"] == "low"
    assert "safe exact code change" in response["suggestion"]


@pytest.mark.asyncio
async def test_successful_analysis_keeps_existing_result():
    context = make_context()
    analysis = {
        "current_behavior": "The parser rejects seconds.",
        "proposed_fix": "Accept the supported time format.",
        "proposed_change": "Update the parser format handling.",
        "suggested_code": "def suggest_time(payload):\n    return True",
    }
    service = SimpleNamespace(analyze=AsyncMock(return_value=analysis))

    await CodeAnalysisStage(service).execute(context)
    context.validation_status = "passed"
    context.validated = True
    await FinalTriageStage().execute(context)
    await ResponseGenerationStage().execute(context)

    response = context.final_response.model_dump()
    assert response["suggestion"] == "Accept the supported time format."
    assert response["proposed_change"] == "Update the parser format handling."
    assert response["suggested_code"] == analysis["suggested_code"]
    assert response["confidence"] == "high"
