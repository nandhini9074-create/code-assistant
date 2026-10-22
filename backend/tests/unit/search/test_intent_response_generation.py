"""Tests verifying that response generation is correct for each intent."""

import pytest
from unittest.mock import AsyncMock

from app.core.enums import IntentType
from app.modules.search.domain.search_domain import RetrievedChunk, SearchContext
from app.modules.search.pipeline.evidence_validation import EvidenceValidationStage
from app.modules.search.pipeline.final_triage import FinalTriageStage
from app.modules.search.pipeline.response_generation import ResponseGenerationStage


def make_chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_hash="chunk-1",
        file_path="app/crud/appointment.py",
        content=(
            "def create_appointment(db, appointment_data):\n"
            "    return Appointment(doctor_id=appointment_data.doctor_id)\n"
        ),
        score=0.95,
        metadata={
            "function_name": "create_appointment",
            "start_line": 10,
            "end_line": 20,
        },
    )


@pytest.mark.asyncio
async def test_retrieve_intent_response_generation():
    chunk = make_chunk()
    context = SearchContext(
        query="How does create_appointment work?",
        repo_name="hospital_management",
        repo_owner="ashwathie",
        intent=IntentType.RETRIEVE,
        retrieved_chunks=[chunk],
        primary_chunk=chunk,
        target_symbol="create_appointment",
    )
    context.analysis_result = {
        "intent": "RETRIEVE",
        "answer": "create_appointment receives db and appointment_data and constructs an Appointment model instance.",
        "suggestion": "create_appointment receives db and appointment_data and constructs an Appointment model instance.",
        "file_path": "app/crud/appointment.py",
        "symbol": "create_appointment",
    }

    # Stage 9: EvidenceValidationStage
    mock_service = AsyncMock()
    await EvidenceValidationStage(mock_service).execute(context)
    assert context.validated is True
    assert context.validation_status == "passed"

    # Stage 13: FinalTriageStage
    await FinalTriageStage().execute(context)
    assert context.triage_result is not None
    assert context.triage_result["ai_suggestion"] == context.analysis_result["answer"]
    assert context.triage_result["proposed_change"] is None
    assert context.triage_result["suggested_code"] is None

    # Stage 14: ResponseGenerationStage
    await ResponseGenerationStage().execute(context)
    response = context.final_response.model_dump()
    assert response["intent"] == "RETRIEVE"
    assert "create_appointment receives db and appointment_data" in response["suggestion"]
    assert response["proposed_change"] is None
    assert response["suggested_code"] is None
    assert response["code_change"] is None
    assert response["current_behavior"] is None


@pytest.mark.asyncio
async def test_fix_bug_intent_response_generation():
    chunk = make_chunk()
    context = SearchContext(
        query="attribute appointment has no object appointment_date",
        repo_name="hospital_management",
        repo_owner="ashwathie",
        intent=IntentType.FIX_BUG,
        retrieved_chunks=[chunk],
        primary_chunk=chunk,
        target_symbol="create_appointment",
    )
    context.analysis_result = {
        "current_behavior": "create_appointment does not initialize appointment_date",
        "likely_cause": "appointment_date is omitted from model instantiation",
        "proposed_fix": "Add appointment_date=appointment_data.appointment_date to Appointment creation",
        "proposed_change": "Pass appointment_date into Appointment",
        "suggested_code": "return Appointment(doctor_id=appointment_data.doctor_id, appointment_date=appointment_data.appointment_date)",
        "code_change": {
            "file_path": "app/crud/appointment.py",
            "start_line": 10,
            "end_line": 12,
            "old_code": "    return Appointment(doctor_id=appointment_data.doctor_id)\n",
            "new_code": "    return Appointment(doctor_id=appointment_data.doctor_id, appointment_date=appointment_data.appointment_date)\n",
        },
    }
    context.validated = True
    context.validation_status = "passed"

    # Stage 13: FinalTriageStage
    await FinalTriageStage().execute(context)
    assert context.triage_result["current_behavior"] == "create_appointment does not initialize appointment_date"
    assert "Pass appointment_date" in context.triage_result["proposed_change"]

    # Stage 14: ResponseGenerationStage
    await ResponseGenerationStage().execute(context)
    response = context.final_response.model_dump()
    assert response["intent"] == "FIX_BUG"
    assert response["current_behavior"] == "create_appointment does not initialize appointment_date"
    assert "Pass appointment_date" in response["proposed_change"]
    assert "safe exact code change" not in response["suggestion"]


@pytest.mark.asyncio
async def test_add_feature_intent_response_generation():
    chunk = make_chunk()
    context = SearchContext(
        query="Add appointment cancellation endpoint",
        repo_name="hospital_management",
        repo_owner="ashwathie",
        intent=IntentType.ADD_FEATURE,
        retrieved_chunks=[chunk],
        primary_chunk=chunk,
        target_symbol="cancel_appointment",
    )
    context.analysis_result = {
        "proposed_change": "Add cancel_appointment route in app/routers/appointments.py",
        "suggested_code": "@router.post('/cancel')\ndef cancel_appointment(): pass",
    }
    context.validated = True
    context.validation_status = "passed"

    # Stage 13: FinalTriageStage
    await FinalTriageStage().execute(context)

    # Stage 14: ResponseGenerationStage
    await ResponseGenerationStage().execute(context)
    response = context.final_response.model_dump()
    assert response["intent"] == "ADD_FEATURE"
    assert "Add cancel_appointment route" in response["proposed_change"]
