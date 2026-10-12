"""
tests/unit/test_deep_search.py

Unit tests for DeepSearchStage in RepoLens.

Covers:
1. Multiple files contain the same function name but only one is on the relevant execution path.
2. Missing frontend field where backend schema/model does not contain the field.
3. Field exists in the model but is missing from the response schema.
4. Field exists in schema but is not populated by the query/service.
5. Runtime error originates in a dependency several files away.
6. Multiple candidates remain genuinely indistinguishable -> AMBIGUOUS.
7. Single strong candidate -> Deep Search is skipped.
8. Deep Search reaches its limits -> no infinite recursion/retry.
9. LLM failure -> deterministic investigation result is preserved and no fabricated root cause is returned.
10. Existing RETRIEVE / ADD_FEATURE / FIX_BUG / OPTIMIZE / REFACTOR behavior remains unchanged.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core.enums import IntentType
from app.modules.search.domain.search_domain import RetrievedChunk, SearchContext
from app.modules.search.pipeline.deep_search import (
    DeepSearchStage,
    InvestigationStrategy,
    ArchitecturalLayer,
    MAX_INVESTIGATION_ROUNDS,
    MAX_CANDIDATES,
)


@pytest.fixture
def deep_search():
    return DeepSearchStage(llm_service=None, hybrid_search=None)


# ---------------------------------------------------------------------------
# Test 1: Same function name in multiple files, only one on execution path
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_same_function_name_resolves_execution_path(deep_search):
    context = SearchContext(
        source_type="git",
        source_location="https://github.com/example/repo",
        query="Error in get_appointment when called from api routes",
        intent=IntentType.FIX_BUG,
        early_exit="EARLY_EXIT_B",
        is_ambiguous=True,
        ambiguous_candidates=[
            {"name": "get_appointment", "file_path": "legacy/utils/helpers.py", "score": 0.5},
            {"name": "get_appointment", "file_path": "app/services/appointment_service.py", "score": 0.5},
        ],
        retrieved_chunks=[
            RetrievedChunk(
                file_path="app/routes/appointments.py",
                content="from app.services.appointment_service import get_appointment\n@app.get('/appointments')\ndef list_appointments():\n    return get_appointment()",
            ),
            RetrievedChunk(
                file_path="app/services/appointment_service.py",
                content="def get_appointment():\n    return db.query()",
            ),
            RetrievedChunk(
                file_path="legacy/utils/helpers.py",
                content="def get_appointment():\n    # unused legacy code\n    pass",
            ),
        ],
    )

    await deep_search.execute(context)

    assert context.early_exit is None
    assert context.is_ambiguous is False
    assert context.target_file == "app/services/appointment_service.py"
    assert context.target_symbol == "get_appointment"


# ---------------------------------------------------------------------------
# Test 2: Missing frontend field where model lacks the field
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_missing_frontend_field_model_lacks_field(deep_search):
    context = SearchContext(
        source_type="git",
        source_location="https://github.com/example/repo",
        query="Appointment has no object attribute appointment_date",
        intent=IntentType.FIX_BUG,
        early_exit="EARLY_EXIT_B",
        is_ambiguous=True,
        ambiguous_candidates=[
            {"name": "appointments.html", "file_path": "templates/appointments.html", "score": 0.6},
            {"name": "Appointment", "file_path": "app/models/appointment.py", "score": 0.6},
        ],
        retrieved_chunks=[
            RetrievedChunk(
                file_path="templates/appointments.html",
                content="<div>{{ appointment.appointment_date }}</div>",
            ),
            RetrievedChunk(
                file_path="app/models/appointment.py",
                content="class Appointment:\n    id = Column(Integer)\n    scheduled_time = Column(DateTime)\n    patient_id = Column(Integer)",
            ),
        ],
    )

    await deep_search.execute(context)

    assert context.early_exit is None
    assert context.is_ambiguous is False
    assert context.target_file == "app/models/appointment.py"
    assert "appointment_date" in context.root_cause_analysis["root_cause"]


# ---------------------------------------------------------------------------
# Test 3: Field exists in model but missing from response schema
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_field_in_model_missing_from_schema(deep_search):
    context = SearchContext(
        source_type="git",
        source_location="https://github.com/example/repo",
        query="Missing attribute appointment_date on appointment response",
        intent=IntentType.FIX_BUG,
        early_exit="EARLY_EXIT_B",
        is_ambiguous=True,
        ambiguous_candidates=[
            {"name": "Appointment", "file_path": "app/models/appointment.py", "score": 0.6},
            {"name": "AppointmentSchema", "file_path": "app/schemas/appointment.py", "score": 0.6},
        ],
        retrieved_chunks=[
            RetrievedChunk(
                file_path="app/models/appointment.py",
                content="class Appointment:\n    id = Column(Integer)\n    appointment_date = Column(DateTime)",
            ),
            RetrievedChunk(
                file_path="app/schemas/appointment.py",
                content="class AppointmentSchema(BaseModel):\n    id: int\n    patient_name: str",
            ),
        ],
    )

    await deep_search.execute(context)

    assert context.early_exit is None
    assert context.is_ambiguous is False
    assert context.target_file == "app/schemas/appointment.py"
    assert "schema" in context.root_cause_analysis["root_cause"].lower()


# ---------------------------------------------------------------------------
# Test 4: Field exists in schema but omitted in query/service
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_field_in_schema_not_populated_by_service(deep_search):
    context = SearchContext(
        source_type="git",
        source_location="https://github.com/example/repo",
        query="Appointment missing field appointment_date in API response",
        intent=IntentType.FIX_BUG,
        early_exit="EARLY_EXIT_B",
        is_ambiguous=True,
        ambiguous_candidates=[
            {"name": "AppointmentResponse", "file_path": "app/schemas/appointment.py", "score": 0.5},
            {"name": "get_appointments", "file_path": "app/services/appointment_service.py", "score": 0.5},
        ],
        retrieved_chunks=[
            RetrievedChunk(
                file_path="app/schemas/appointment.py",
                content="class AppointmentResponse(BaseModel):\n    id: int\n    appointment_date: str",
            ),
            RetrievedChunk(
                file_path="app/services/appointment_service.py",
                content="def get_appointments():\n    return {'id': 1, 'notes': 'Checkup'}",
            ),
        ],
    )

    await deep_search.execute(context)

    assert context.early_exit is None
    assert context.is_ambiguous is False
    assert context.target_file == "app/services/appointment_service.py"


# ---------------------------------------------------------------------------
# Test 5: Runtime error originates in dependency several files away
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_runtime_error_deep_dependency(deep_search):
    context = SearchContext(
        source_type="git",
        source_location="https://github.com/example/repo",
        query="TypeError in booking_flow calling calculate_total",
        intent=IntentType.FIX_BUG,
        early_exit="EARLY_EXIT_B",
        is_ambiguous=True,
        ambiguous_candidates=[
            {"name": "booking_flow", "file_path": "app/routes/booking.py", "score": 0.5},
            {"name": "calculate_total", "file_path": "app/pricing/calculator.py", "score": 0.5},
        ],
        retrieved_chunks=[
            RetrievedChunk(
                file_path="app/routes/booking.py",
                content="from app.pricing.calculator import calculate_total\ndef booking_flow():\n    calculate_total('invalid')",
            ),
            RetrievedChunk(
                file_path="app/pricing/calculator.py",
                content="def calculate_total(amount):\n    return amount + 10  # raises TypeError if string",
            ),
        ],
    )

    await deep_search.execute(context)

    assert context.early_exit is None
    assert context.target_file == "app/pricing/calculator.py"


# ---------------------------------------------------------------------------
# Test 6: Multiple candidates genuinely indistinguishable -> AMBIGUOUS
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_genuinely_indistinguishable_candidates_remain_ambiguous(deep_search):
    context = SearchContext(
        source_type="git",
        source_location="https://github.com/example/repo",
        query="format_date",
        intent=IntentType.RETRIEVE,
        early_exit="EARLY_EXIT_B",
        is_ambiguous=True,
        ambiguous_candidates=[
            {"name": "format_date", "file_path": "pkg_a/utils.py", "score": 0.5},
            {"name": "format_date", "file_path": "pkg_b/utils.py", "score": 0.5},
        ],
        retrieved_chunks=[
            RetrievedChunk(file_path="pkg_a/utils.py", content="def format_date(d): return str(d)"),
            RetrievedChunk(file_path="pkg_b/utils.py", content="def format_date(d): return str(d)"),
        ],
    )

    await deep_search.execute(context)

    assert context.early_exit == "EARLY_EXIT_B"
    assert context.is_ambiguous is True


# ---------------------------------------------------------------------------
# Test 7: Single strong candidate -> Deep Search is skipped
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_single_strong_candidate_deep_search_skipped(deep_search):
    primary = RetrievedChunk(
        file_path="app/main.py",
        content="def main(): pass",
        score=0.95,
    )
    context = SearchContext(
        source_type="git",
        source_location="https://github.com/example/repo",
        query="main function entry point",
        intent=IntentType.RETRIEVE,
        primary_chunk=primary,
        early_exit=None,
        is_ambiguous=False,
        ambiguous_candidates=[],
        retrieved_chunks=[primary],
    )

    await deep_search.execute(context)

    # Context remains unchanged
    assert context.primary_chunk == primary
    assert context.deep_search_result is None


# ---------------------------------------------------------------------------
# Test 8: Deep Search bounded limits (no infinite loops)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_bounded_investigation_limits(deep_search):
    chunks = [
        RetrievedChunk(file_path=f"file_{i}.py", content=f"def func_{i}(): pass")
        for i in range(20)
    ]
    context = SearchContext(
        source_type="git",
        source_location="https://github.com/example/repo",
        query="TypeError in func across multiple files",
        intent=IntentType.FIX_BUG,
        early_exit="EARLY_EXIT_B",
        is_ambiguous=True,
        retrieved_chunks=chunks,
    )

    await deep_search.execute(context)

    # Ensure investigated candidates pool was bounded to configured max
    assert len(context.investigated_candidates) <= 15


# ---------------------------------------------------------------------------
# Test 9: LLM failure -> deterministic investigation preserved
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_llm_failure_falls_back_to_deterministic():
    mock_provider = MagicMock()
    mock_provider.complete = AsyncMock(side_effect=RuntimeError("LLM API timeout"))
    mock_llm_service = MagicMock()
    mock_llm_service.provider = mock_provider

    ds = DeepSearchStage(llm_service=mock_llm_service)

    context = SearchContext(
        source_type="git",
        source_location="https://github.com/example/repo",
        query="Appointment has no object attribute appointment_date",
        intent=IntentType.FIX_BUG,
        early_exit="EARLY_EXIT_B",
        is_ambiguous=True,
        ambiguous_candidates=[
            {"name": "appointments.html", "file_path": "templates/appointments.html", "score": 0.5},
            {"name": "Appointment", "file_path": "app/models/appointment.py", "score": 0.5},
        ],
        retrieved_chunks=[
            RetrievedChunk(
                file_path="templates/appointments.html",
                content="<div>{{ appointment.appointment_date }}</div>",
            ),
            RetrievedChunk(
                file_path="app/models/appointment.py",
                content="class Appointment:\n    id = Column(Integer)\n    scheduled_time = Column(DateTime)",
            ),
        ],
    )

    await ds.execute(context)

    # Resolution succeeds via deterministic evidence without crashing
    assert context.early_exit is None
    assert context.target_file == "app/models/appointment.py"
    assert context.root_cause_analysis is not None


# ---------------------------------------------------------------------------
# Test 10: Existing intents unaffected
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_existing_intents_unaffected(deep_search):
    for intent in [IntentType.RETRIEVE, IntentType.ADD_FEATURE, IntentType.OPTIMIZE, IntentType.REFACTOR]:
        primary = RetrievedChunk(file_path="app/feature.py", content="def add(): pass", score=0.9)
        context = SearchContext(
            source_type="git",
            source_location="https://github.com/example/repo",
            query="add new endpoint",
            intent=intent,
            primary_chunk=primary,
            early_exit=None,
            is_ambiguous=False,
            retrieved_chunks=[primary],
        )
        await deep_search.execute(context)
        assert context.deep_search_result is None
        assert context.primary_chunk == primary
