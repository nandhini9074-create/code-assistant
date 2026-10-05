from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.enums import IntentType
from app.modules.code_analysis.analyzers.fix_bug_analyzer import (
    FixBugAnalyzer,
    _has_concrete_evidence,
)
from app.modules.search.domain.search_domain import RetrievedChunk, SearchContext
from app.modules.search.pipeline.code_retrieval import (
    CodeRetrievalStage,
    _extract_bug_signals,
)
from app.modules.search.pipeline.context_builder import ContextBuilderStage
from app.modules.search.pipeline.response_generation import ResponseGenerationStage


def _chunk(
    chunk_hash: str,
    file_path: str,
    content: str,
    symbol: str,
    score: float = 0.8,
    related: list[str] | None = None,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_hash=chunk_hash,
        file_path=file_path,
        content=content,
        score=score,
        metadata={
            "function_name": symbol,
            "start_line": 1,
            "end_line": len(content.splitlines()),
            "_fix_bug_related_hashes": related or [],
        },
    )


@pytest.mark.asyncio
async def test_fix_bug_retrieval_expands_across_related_files():
    primary = _chunk(
        "frontend",
        "frontend/appointments.js",
        'import { saveAppointment } from "./appointment_service";\n'
        "function selectAppointmentDate(date) { saveAppointment(date); }",
        "selectAppointmentDate",
    )
    related = _chunk(
        "service",
        "backend/appointment_service.py",
        "from app.models.appointment import Appointment\n"
        "def saveAppointment(date):\n    return persist(date)",
        "saveAppointment",
    )
    model = _chunk(
        "model",
        "backend/models/appointment.py",
        "class Appointment:\n    date = None",
        "Appointment",
    )

    class FakeHybridSearch:
        def __init__(self):
            self.queries = []

        async def search(self, context, limit):
            self.queries.append(context.query)
            if len(self.queries) == 1:
                return [primary]
            if len(self.queries) == 2:
                return [related]
            return [model]

    hybrid = FakeHybridSearch()
    context = SearchContext(
        query="Fix the appointment date selection error",
        repo_name="demo",
        qdrant_collection="demo",
        intent=IntentType.FIX_BUG,
    )

    with patch(
        "app.modules.search.pipeline.code_retrieval.generate_embeddings",
        new=AsyncMock(side_effect=[[[0.1]], [[0.2]], [[0.3]]]),
    ):
        await CodeRetrievalStage(hybrid).execute(context)

    assert len(hybrid.queries) == 3
    expanded_query = hybrid.queries[1].lower()
    assert all(term in expanded_query for term in ("appointment", "date", "selection"))
    assert "selectappointmentdate" in expanded_query
    assert "appointment" in hybrid.queries[2].lower()
    assert context.query == "Fix the appointment date selection error"
    assert {chunk.chunk_hash for chunk in context.retrieved_chunks} == {
        "frontend",
        "service",
        "model",
    }
    assert context.retrieved_chunks[0].metadata["_fix_bug_related_hashes"]


@pytest.mark.asyncio
async def test_fix_bug_context_labels_primary_related_and_supporting_code():
    primary = _chunk(
        "primary",
        "frontend/appointments.js",
        "function selectAppointmentDate() { return null; }",
        "selectAppointmentDate",
        related=["related"],
    )
    related = _chunk(
        "related",
        "backend/appointment_service.py",
        "def saveAppointment(date): return persist(date)",
        "saveAppointment",
        related=["primary"],
    )
    supporting = _chunk(
        "supporting",
        "backend/appointment_model.py",
        "class Appointment: date = None",
        "Appointment",
    )
    context = SearchContext(
        query="Fix appointment date selection error",
        repo_name="demo",
        intent=IntentType.FIX_BUG,
        retrieved_chunks=[primary, related, supporting],
        primary_chunk=primary,
    )

    with patch(
        "app.modules.search.pipeline.context_builder.build_toon_llm_context",
        side_effect=lambda snippets, code_blocks: "\n".join(code_blocks),
    ):
        await ContextBuilderStage().execute(context)

    assert [snippet["role"] for snippet in context.code_snippets] == [
        "PRIMARY",
        "RELATED",
        "SUPPORTING",
    ]
    assert "PRIMARY CODE" in context.llm_context
    assert "RELATED CODE" in context.llm_context
    assert "SUPPORTING CODE" in context.llm_context


@pytest.mark.asyncio
async def test_fix_bug_analyzer_marks_unsupported_diagnosis_unavailable():
    raw = {
        "analysis_status": "OK",
        "evidence_summary": "The function has suspicious logic.",
        "current_behavior": "The function returns an empty result.",
        "problematic_code": "return None",
        "likely_cause": "The selection is not handled.",
        "proposed_fix": "Handle the selected date.",
        "proposed_change": "Update the selection handler.",
        "code_change": {
            "file_path": "backend/appointment_service.py",
            "symbol": "saveAppointment",
            "start_line": 1,
            "end_line": 1,
            "old_code": "def saveAppointment(date):",
            "new_code": "def saveAppointment(date): return date",
        },
        "suggested_code": "def saveAppointment(date): return date",
    }
    llm_service = SimpleNamespace(
        provider=SimpleNamespace(complete_json=AsyncMock(return_value=raw))
    )
    context = SearchContext(
        query="Fix the appointment date selection error",
        intent=IntentType.FIX_BUG,
        retrieved_chunks=[
            _chunk(
                "service",
                "backend/appointment_service.py",
                "def saveAppointment(date):\n    return None",
                "saveAppointment",
            )
        ],
    )

    result = await FixBugAnalyzer(llm_service).analyze(context)

    assert result.analysis["analysis_status"] == "UNAVAILABLE"
    assert result.analysis["code_change"] is None
    assert result.analysis["suggested_code"] == ""
    assert not _has_concrete_evidence(raw, context)


def test_bug_signal_extraction_keeps_entities_fields_actions_and_errors():
    signals = _extract_bug_signals("Fix the appointment date selection error")

    assert "appointment" in signals["entities"]
    assert "date" in signals["fields"]
    assert "selection" in signals["actions"]
    assert "error" in signals["errors"]


@pytest.mark.asyncio
async def test_unavailable_bug_analysis_is_returned_without_a_target_or_patch():
    context = SearchContext(
        query="Fix the appointment date selection error",
        repo_name="demo",
        intent=IntentType.FIX_BUG,
        analysis_result={
            "analysis_status": "UNAVAILABLE",
            "evidence_summary": "The retrieved chunks do not connect the date field to the error.",
            "code_change": None,
        },
        patch_validation={"status": "not_run"},
    )

    await ResponseGenerationStage().execute(context)
    response = context.final_response.model_dump()

    assert response["patch_validation"]["analysis_status"] == "UNAVAILABLE"
    assert response["target"] == {"file_path": None, "symbol": None}
    assert response["code_change"] is None
    assert response["suggested_code"] is None
    assert response["suggested_patch"] is None


def test_fix_bug_evidence_requires_report_signal_target_and_exact_source():
    context = SearchContext(
        query="Fix the appointment date selection error",
        intent=IntentType.FIX_BUG,
        retrieved_chunks=[
            _chunk(
                "service",
                "backend/appointment_service.py",
                "def saveAppointment(date):\n    return None",
                "saveAppointment",
            )
        ],
    )
    analysis = {
        "evidence_summary": (
            "backend/appointment_service.py::saveAppointment ignores the appointment date."
        ),
        "code_change": {
            "file_path": "backend/appointment_service.py",
            "symbol": "saveAppointment",
            "old_code": "def saveAppointment(date):",
            "new_code": "def saveAppointment(date): return date",
        },
    }

    assert _has_concrete_evidence(analysis, context)