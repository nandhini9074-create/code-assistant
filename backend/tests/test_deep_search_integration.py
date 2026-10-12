"""
tests/test_deep_search_integration.py

Integration tests for the Deep Search branch and normal-pipeline regression.

Coverage:
 1.  Ordinary FIX_BUG requests stay on the normal pipeline.
 2.  Non-FIX_BUG intents never invoke Deep Search.
 3.  A qualifying cross-file bug selects Deep Search before normal retrieval.
 4.  The resolved qdrant_collection is passed correctly.
 5.  Deep Search does not invoke normal retrieval or analysis afterward.
 6.  Missing source provider returns 'unavailable', not a fabricated diagnosis.
 7.  Missing targets or insufficient evidence return 'incomplete'.
 8.  Retrieval and assessment failures produce explicit terminal results.
 9.  Follow-up investigation stops at the configured limit.
10.  Duplicate targets and retrieved evidence are handled correctly.
11.  A field-mapping mismatch does not automatically generate a DB-column addition.
12.  Response generation correctly presents complete, incomplete, unavailable results.
13.  Existing normal-pipeline tests continue to pass unchanged.
"""

from __future__ import annotations

import pytest
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from app.core.enums import IntentType
from app.modules.search.domain.search_domain import SearchContext
from app.modules.search.pipeline.deep_search_decision import decide_deep_search
from app.modules.search.pipeline.intent_classification import (
    IntentClassificationStage,
)
from app.modules.search.pipeline.deep_search import (
    DeepSearchStage,
    DeepSearchWorkflow,
)
from app.modules.search.pipeline.deep_search_retriever import DeepSearchRetriever
from app.modules.search.pipeline.deep_search_assessor import DeepSearchAssessor
from app.modules.search.pipeline.dependency_graph import build_dependency_graph
from app.modules.search.pipeline.response_generation import ResponseGenerationStage


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def source_files() -> dict[str, str]:
    return {
        "app/routes.py": (
            "from app.services import get_appointment\n\n"
            "def appointment_route():\n"
            "    return get_appointment()\n"
        ),
        "app/services.py": (
            "def get_appointment():\n"
            "    return None\n"
        ),
        "app/models.py": (
            "class Appointment:\n"
            "    def __init__(self, appointment_time):\n"
            "        self.appointment_time = appointment_time\n"
        ),
        "templates/appointments.html": (
            "{{ appointment.appointment_date }}\n"
        ),
    }


@pytest.fixture
def graph(source_files):
    return build_dependency_graph(source_files)


@pytest.fixture
def retrieval_state() -> dict[str, str]:
    return {
        "repo_name": "owner_hospital",
        "collection_name": "repo_owner_hospital",
    }


@pytest.fixture
def retrieved_chunks() -> list[dict]:
    return [
        {
            "path": "app/services.py",
            "content": (
                "def get_appointment():\n"
                "    return None\n"
            ),
            "line_start": 1,
            "line_end": 2,
        }
    ]


def _make_context(
    *,
    query: str,
    intent: IntentType | None = None,
    intent_parameters: dict | None = None,
    qdrant_collection: str | None = "repo_owner_hospital",
    repo_name: str = "hospital",
    repo_owner: str = "owner",
    source_type: str = "git",
    source_location: str = "https://github.com/owner/hospital",
) -> SearchContext:
    ctx = SearchContext(
        query=query,
        source_type=source_type,
        source_location=source_location,
    )
    ctx.intent = intent
    ctx.intent_parameters = intent_parameters or {}
    ctx.qdrant_collection = qdrant_collection
    ctx.repo_name = repo_name
    ctx.repo_owner = repo_owner
    return ctx


# ===========================================================================
# Test 1: Ordinary FIX_BUG stays on the normal pipeline
# ===========================================================================

def test_decide_deep_search_rejects_ordinary_fix_bug():
    """Plain bug reports with no cross-file signals must not select Deep Search."""
    decision = decide_deep_search(
        intent="FIX_BUG",
        query="fix the login bug",
    )
    assert decision.selected is False


def test_decide_deep_search_rejects_generic_error_queries():
    """Generic error/fix words alone must not trigger Deep Search."""
    for query in [
        "there is an error in my code",
        "fix the issue",
        "debug this problem",
        "not working",
    ]:
        decision = decide_deep_search(intent="FIX_BUG", query=query)
        assert decision.selected is False, (
            f"Query {query!r} must not select Deep Search."
        )


# ===========================================================================
# Test 2: Non-FIX_BUG intents never invoke Deep Search
# ===========================================================================

def test_decide_deep_search_rejects_non_fix_bug_intents():
    """Cross-file wording must not activate Deep Search for other intents."""
    cross_file_query = (
        "find where appointment_date is defined across multiple files"
    )
    for intent in ["RETRIEVE", "ADD_FEATURE", "OPTIMIZE", "REFACTOR"]:
        decision = decide_deep_search(intent=intent, query=cross_file_query)
        assert decision.selected is False, (
            f"Intent {intent} must never select Deep Search."
        )


@pytest.mark.asyncio
async def test_deep_search_stage_skips_non_fix_bug():
    """DeepSearchStage must not run the workflow for non-FIX_BUG intents."""
    workflow = MagicMock()
    stage = DeepSearchStage(workflow=workflow)

    ctx = _make_context(
        query="add a new feature",
        intent=IntentType.ADD_FEATURE,
        intent_parameters={"deep_search_requested": True},
    )

    await stage.execute(ctx)

    workflow.run.assert_not_called()
    assert ctx.deep_search_result is None


# ===========================================================================
# Test 3: Qualifying cross-file bug selects Deep Search
# ===========================================================================

def test_decide_deep_search_selects_cross_file_bug():
    """Queries with cross-file investigation signals must select Deep Search."""
    qualifying_queries = [
        "trace the data flow across multiple files for the appointment bug",
        "investigate across files why appointment_date is undefined",
        "deep search for the root cause of this AttributeError",
        "the wrong field is passed from the template to the model",
        "missing attribute appointment_date — trace the full flow",
    ]
    for query in qualifying_queries:
        decision = decide_deep_search(intent="FIX_BUG", query=query)
        assert decision.selected is True, (
            f"Query {query!r} should select Deep Search."
        )


@pytest.mark.asyncio
async def test_intent_classification_sets_deep_search_in_parameters():
    """IntentClassificationStage must store the flag in intent_parameters."""
    mock_llm = AsyncMock()

    class _FakeResult:
        intent = "FIX_BUG"
        parameters = {}
        confidence = 0.9

    mock_llm.classify_intent = AsyncMock(return_value=_FakeResult())
    stage = IntentClassificationStage(llm_service=mock_llm)

    ctx = _make_context(
        query=(
            "undefined attribute appointment_date — trace the data flow "
            "across the template, route, and model"
        ),
    )

    await stage.execute(ctx)

    assert ctx.intent == IntentType.FIX_BUG
    params = ctx.intent_parameters
    assert isinstance(params, dict)
    assert params.get("deep_search_requested") is True
    assert "deep_search_reason" in params


# ===========================================================================
# Test 4: The resolved qdrant_collection is passed correctly
# ===========================================================================

@pytest.mark.asyncio
async def test_deep_search_stage_passes_qdrant_collection():
    """DeepSearchStage must map context.qdrant_collection → state['collection_name']."""
    captured_states: list[dict] = []

    def mock_run(state: dict) -> dict:
        captured_states.append(dict(state))
        return {
            "status": "unavailable",
            "intent": "FIX_BUG",
            "diagnosis": None,
            "confidence": 0.0,
            "evidence": [],
            "retrieved_chunks": [],
            "searched_targets": [],
            "missing_targets": [],
            "rounds": 0,
            "reason": "No source provider configured.",
        }

    workflow = MagicMock()
    workflow.run = mock_run
    stage = DeepSearchStage(workflow=workflow)

    ctx = _make_context(
        query="trace the bug across files — undefined attribute",
        intent=IntentType.FIX_BUG,
        intent_parameters={"deep_search_requested": True},
        qdrant_collection="repo_owner_hospital",
        repo_name="hospital",
    )

    await stage.execute(ctx)

    assert len(captured_states) == 1
    state = captured_states[0]
    assert state["collection_name"] == "repo_owner_hospital"
    assert state["repo_name"] == "hospital"
    assert state["deep_search_requested"] is True


# ===========================================================================
# Test 5: Deep Search does not invoke normal retrieval or analysis afterward
# ===========================================================================

@pytest.mark.asyncio
async def test_deep_search_stage_sets_early_exit_complete():
    """After Deep Search, early_exit must be 'DEEP_SEARCH_COMPLETE'."""
    def mock_run(state: dict) -> dict:
        return {
            "status": "unavailable",
            "intent": "FIX_BUG",
            "diagnosis": None,
            "confidence": 0.0,
            "evidence": [],
            "retrieved_chunks": [],
            "searched_targets": [],
            "missing_targets": [],
            "rounds": 0,
            "reason": "No source provider.",
        }

    workflow = MagicMock()
    workflow.run = mock_run
    stage = DeepSearchStage(workflow=workflow)

    ctx = _make_context(
        query="trace across files — undefined field",
        intent=IntentType.FIX_BUG,
        intent_parameters={"deep_search_requested": True},
    )

    await stage.execute(ctx)

    assert ctx.early_exit == "DEEP_SEARCH_COMPLETE"
    assert not ctx.retrieved_chunks
    assert ctx.analysis_result is None


# ===========================================================================
# Test 6: Missing source provider returns 'unavailable'
# ===========================================================================

def test_workflow_returns_unavailable_without_source_provider():
    """Without a source_provider, the workflow must return status='unavailable'."""
    workflow = DeepSearchWorkflow(
        source_provider=None,
        search_adapter=None,
        assessment_adapter=None,
    )

    result = workflow.run({
        "query": "trace appointment_date across files",
        "intent": "FIX_BUG",
        "deep_search_requested": True,
        "repo_name": "hospital",
        "collection_name": "repo_owner_hospital",
    })

    assert result["status"] == "unavailable"
    assert result["diagnosis"] is None


def test_workflow_returns_unavailable_for_missing_collection():
    """A missing collection must immediately produce status='unavailable'."""
    workflow = DeepSearchWorkflow()

    result = workflow.run({
        "query": "trace bug across files",
        "intent": "FIX_BUG",
        "deep_search_requested": True,
        "repo_name": "hospital",
        # collection_name intentionally omitted
    })

    assert result["status"] == "unavailable"
    assert result["diagnosis"] is None


# ===========================================================================
# Test 7: Missing targets or insufficient evidence return 'incomplete'
# ===========================================================================

def test_assessor_returns_incomplete_without_adapter(retrieved_chunks):
    """Without an assessment adapter the status must be 'incomplete'."""
    assessor = DeepSearchAssessor()
    result = assessor.assess({
        "query": "undefined appointment_date attribute",
        "retrieved_chunks": retrieved_chunks,
        "rounds": 0,
        "max_rounds": 3,
    })
    assert result["status"] == "incomplete"
    assert result["diagnosis"] is None


def test_retriever_returns_insufficient_evidence_when_no_chunks_match(
    retrieval_state,
):
    """When the adapter returns chunks for wrong files, all targets are missing."""
    retriever = DeepSearchRetriever(
        search_adapter=lambda req: [
            {
                "path": "app/unrelated.py",
                "content": "def nothing(): pass",
                "line_start": 1,
                "line_end": 1,
            }
        ],
    )

    result = retriever.retrieve(
        query="appointment_date undefined",
        targets=[{"path": "app/models.py", "name": "Appointment", "kind": "class"}],
        state=retrieval_state,
    )

    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert "app/models.py" in result["missing_targets"]
    assert result["retrieved_chunks"] == []


# ===========================================================================
# Test 8: Retrieval and assessment failures produce explicit terminal results
# ===========================================================================

def test_assessor_returns_unavailable_when_adapter_raises(retrieved_chunks):
    """An adapter exception during assessment must produce status='unavailable'."""
    def failing_adapter(payload):
        raise RuntimeError("Simulated adapter failure")

    assessor = DeepSearchAssessor(assessment_adapter=failing_adapter)
    result = assessor.assess({
        "query": "appointment_date attribute error",
        "retrieved_chunks": retrieved_chunks,
        "rounds": 0,
        "max_rounds": 3,
    })

    assert result["status"] == "unavailable"
    assert result["diagnosis"] is None


def test_retriever_returns_unavailable_when_adapter_raises(retrieval_state):
    """A search adapter exception must produce UNAVAILABLE retrieval status."""
    def failing_adapter(req):
        raise ConnectionError("Simulated backend failure")

    retriever = DeepSearchRetriever(search_adapter=failing_adapter)
    result = retriever.retrieve(
        query="appointment_date error",
        targets=["app/models.py"],
        state=retrieval_state,
    )

    assert result["status"] == "UNAVAILABLE"
    assert result["retrieved_count"] == 0


def test_retriever_returns_unavailable_without_adapter(retrieval_state):
    """Without a search adapter the retriever must return UNAVAILABLE immediately."""
    retriever = DeepSearchRetriever()
    result = retriever.retrieve(
        query="appointment_date error",
        targets=["app/models.py"],
        state=retrieval_state,
    )
    assert result["status"] == "UNAVAILABLE"
    assert result["retrieved_count"] == 0


# ===========================================================================
# Test 9: Follow-up investigation stops at the configured limit
# ===========================================================================

def test_assessor_stops_follow_up_at_max_rounds(graph, retrieved_chunks):
    """When rounds >= max_rounds - 1, the assessor must return 'incomplete'."""
    def always_wants_more(payload):
        return {
            "is_sufficient": False,
            "diagnosis": None,
            "confidence": 0.3,
            "evidence": [],
            "follow_up_targets": ["file:app/models.py"],
            "follow_up_query": "Inspect models.",
            "reason": "More evidence needed.",
        }

    assessor = DeepSearchAssessor(
        assessment_adapter=always_wants_more,
        max_rounds=3,
    )

    result = assessor.assess({
        "query": "appointment_date field mismatch",
        "retrieved_chunks": retrieved_chunks,
        "dependency_graph": graph,
        "rounds": 2,
        "max_rounds": 3,
    })

    assert result["status"] == "incomplete"
    assert result["follow_up_targets"] == []


def test_workflow_respects_max_rounds_limit(source_files):
    """The workflow must not produce 'complete' when max_rounds is exhausted."""
    call_count = {"n": 0}

    def counting_adapter(payload):
        call_count["n"] += 1
        return {
            "is_sufficient": False,
            "diagnosis": None,
            "confidence": 0.2,
            "evidence": [],
            "follow_up_targets": ["file:app/models.py"],
            "follow_up_query": "Keep looking.",
            "reason": "Not done yet.",
        }

    def source_provider(state):
        return source_files

    workflow = DeepSearchWorkflow(
        source_provider=source_provider,
        assessment_adapter=counting_adapter,
        max_rounds=2,
    )

    result = workflow.run({
        "query": "appointment_date is undefined — trace across files",
        "intent": "FIX_BUG",
        "deep_search_requested": True,
        "repo_name": "hospital",
        "collection_name": "repo_owner_hospital",
    })

    assert result["status"] in {"incomplete", "unavailable"}
    assert result["diagnosis"] is None
    assert call_count["n"] <= 2


# ===========================================================================
# Test 10: Duplicate targets and retrieved evidence are handled correctly
# ===========================================================================

def test_retriever_deduplicates_chunks(retrieval_state):
    """Chunks with identical path/content/line_start must not be duplicated."""
    duplicate_chunk = {
        "path": "app/services.py",
        "content": "def get_appointment():\n    return None\n",
        "line_start": 1,
        "line_end": 2,
    }

    retriever = DeepSearchRetriever(
        search_adapter=lambda req: [
            duplicate_chunk,
            duplicate_chunk,
            duplicate_chunk,
        ],
    )

    result = retriever.retrieve(
        query="appointment error",
        targets=[{"path": "app/services.py", "name": "get_appointment", "kind": "function"}],
        state=retrieval_state,
    )

    assert result["status"] == "SUCCESS"
    assert result["retrieved_count"] == 1


def test_assessor_deduplicates_verified_evidence(retrieved_chunks):
    """Repeated identical evidence citations must be collapsed to one."""
    def repeated_adapter(payload):
        evidence_item = {
            "path": "app/services.py",
            "quote": "return None",
            "claim": "The function returns None.",
            "line_start": 2,
            "line_end": 2,
        }
        return {
            "is_sufficient": True,
            "diagnosis": "The function returns None unexpectedly.",
            "confidence": 0.85,
            "evidence": [evidence_item, evidence_item, evidence_item],
            "follow_up_targets": [],
            "reason": "Evidence confirmed.",
        }

    assessor = DeepSearchAssessor(assessment_adapter=repeated_adapter)
    result = assessor.assess({
        "query": "appointment function returns None",
        "retrieved_chunks": retrieved_chunks,
        "rounds": 0,
        "max_rounds": 3,
    })

    assert result["status"] == "complete"
    assert len(result["evidence"]) == 1


# ===========================================================================
# Test 11: Field-mapping mismatch does not generate a DB-column addition
# ===========================================================================

def test_assessor_does_not_fabricate_model_field():
    """
    A template/model mismatch diagnosis must describe the mismatch, not
    automatically propose adding a database column.
    """
    chunks = [
        {
            "path": "app/models.py",
            "content": (
                "class Appointment:\n"
                "    def __init__(self, appointment_time):\n"
                "        self.appointment_time = appointment_time\n"
            ),
            "line_start": 1,
            "line_end": 3,
        },
        {
            "path": "templates/appointments.html",
            "content": "{{ appointment.appointment_date }}\n",
            "line_start": 1,
            "line_end": 1,
        },
    ]

    def mismatch_adapter(payload):
        return {
            "is_sufficient": True,
            "diagnosis": (
                "The template references 'appointment.appointment_date' "
                "but the Appointment model only exposes 'appointment_time'. "
                "This is a field-name mismatch between the template and model."
            ),
            "confidence": 0.88,
            "evidence": [
                {
                    "path": "app/models.py",
                    "quote": "self.appointment_time = appointment_time",
                    "claim": (
                        "The model defines appointment_time, not appointment_date."
                    ),
                    "line_start": 3,
                    "line_end": 3,
                },
                {
                    "path": "templates/appointments.html",
                    "quote": "{{ appointment.appointment_date }}",
                    "claim": "The template references the non-existent field.",
                    "line_start": 1,
                    "line_end": 1,
                },
            ],
            "follow_up_targets": [],
            "reason": "Field-name mismatch identified from source evidence.",
        }

    assessor = DeepSearchAssessor(assessment_adapter=mismatch_adapter)
    result = assessor.assess({
        "query": (
            "AttributeError: appointment_date — "
            "trace the field across the template and model"
        ),
        "retrieved_chunks": chunks,
        "rounds": 0,
        "max_rounds": 3,
    })

    assert result["status"] == "complete"
    assert result["diagnosis"] is not None
    assert "appointment_date" in result["diagnosis"].lower()
    assert "mismatch" in result["diagnosis"].lower()

    # Guard: evidence must not propose adding a DB column.
    for ev in result["evidence"]:
        claim_lower = ev["claim"].lower()
        assert "column" not in claim_lower, (
            "Evidence must not reference a database column addition."
        )


# ===========================================================================
# Test 12: Response generation presents complete, incomplete, unavailable
# ===========================================================================

def _make_deep_search_context(
    *,
    deep_search_result: dict,
    query: str = "trace appointment_date across files",
) -> SearchContext:
    ctx = SearchContext(
        query=query,
        source_type="git",
        source_location="https://github.com/owner/hospital",
    )
    ctx.intent = IntentType.FIX_BUG
    ctx.intent_parameters = {
        "deep_search_requested": True,
        "deep_search_reason": "Cross-file investigation signal.",
    }
    ctx.qdrant_collection = "repo_owner_hospital"
    ctx.repo_name = "hospital"
    ctx.repo_owner = "owner"
    ctx.deep_search_result = deep_search_result
    ctx.early_exit = "DEEP_SEARCH_COMPLETE"
    return ctx


@pytest.mark.asyncio
async def test_response_generation_presents_complete_result():
    """ResponseGenerationStage must present the diagnosis for status='complete'."""
    result = {
        "status": "complete",
        "intent": "FIX_BUG",
        "repo_name": "hospital",
        "diagnosis": (
            "The template references appointment.appointment_date but "
            "the model only exposes appointment_time. This is a field mismatch."
        ),
        "confidence": 0.88,
        "evidence": [
            {
                "path": "app/models.py",
                "quote": "self.appointment_time = appointment_time",
                "claim": "The model defines appointment_time only.",
                "line_start": 3,
            }
        ],
        "retrieved_chunks": [],
        "searched_targets": ["app/models.py", "templates/appointments.html"],
        "missing_targets": [],
        "rounds": 1,
        "reason": "Mismatch confirmed in source.",
    }

    ctx = _make_deep_search_context(deep_search_result=result)
    stage = ResponseGenerationStage()
    await stage.execute(ctx)

    response = ctx.final_response
    assert response is not None
    assert response.intent == "FIX_BUG"
    assert response.suggestion is not None
    assert response.confidence in {"high", "medium"}
    assert response.root_cause_analysis is not None
    assert response.root_cause_analysis["status"] == "complete"
    assert response.patch_validation["deep_search"] is True
    assert response.patch_validation["repository_modified"] is False
    assert response.code_change is None


@pytest.mark.asyncio
async def test_response_generation_presents_incomplete_result():
    """ResponseGenerationStage must present an explanation for status='incomplete'."""
    result = {
        "status": "incomplete",
        "intent": "FIX_BUG",
        "repo_name": "hospital",
        "diagnosis": None,
        "confidence": 0.0,
        "evidence": [],
        "retrieved_chunks": [],
        "searched_targets": ["app/models.py"],
        "missing_targets": ["templates/appointments.html"],
        "rounds": 2,
        "reason": "Evidence was insufficient to establish a root cause.",
    }

    ctx = _make_deep_search_context(deep_search_result=result)
    stage = ResponseGenerationStage()
    await stage.execute(ctx)

    response = ctx.final_response
    assert response is not None
    assert response.confidence == "low"
    assert response.code_change is None
    assert response.root_cause_analysis["status"] == "incomplete"
    assert response.patch_validation["repository_modified"] is False
    assert response.suggestion is not None


@pytest.mark.asyncio
async def test_response_generation_presents_unavailable_result():
    """ResponseGenerationStage must explain the failure for status='unavailable'."""
    result = {
        "status": "unavailable",
        "intent": "FIX_BUG",
        "repo_name": "hospital",
        "diagnosis": None,
        "confidence": 0.0,
        "evidence": [],
        "retrieved_chunks": [],
        "searched_targets": [],
        "missing_targets": [],
        "rounds": 0,
        "reason": "No read-only repository source provider is configured.",
    }

    ctx = _make_deep_search_context(deep_search_result=result)
    stage = ResponseGenerationStage()
    await stage.execute(ctx)

    response = ctx.final_response
    assert response is not None
    assert response.confidence == "low"
    assert response.code_change is None
    assert response.root_cause_analysis["status"] == "unavailable"
    assert response.suggestion is not None
    assert len(response.suggestion) > 0


# ===========================================================================
# Test 13: Normal-pipeline tests continue to pass unchanged
# ===========================================================================

def test_decide_deep_search_preserves_non_fix_bug_routing():
    """Decision must return selected=False for non-FIX_BUG regardless of wording."""
    decision = decide_deep_search(
        intent="RETRIEVE",
        query="deep search for the undefined field across multiple files",
    )
    assert decision.selected is False


@pytest.mark.asyncio
async def test_deep_search_stage_does_not_run_for_normal_fix_bug():
    """A FIX_BUG request without deep_search_requested must not touch the workflow."""
    workflow = MagicMock()
    stage = DeepSearchStage(workflow=workflow)

    ctx = _make_context(
        query="fix the login error",
        intent=IntentType.FIX_BUG,
        intent_parameters={"deep_search_requested": False},
    )

    await stage.execute(ctx)

    workflow.run.assert_not_called()
    assert ctx.early_exit is None
    assert ctx.deep_search_result is None


@pytest.mark.asyncio
async def test_deep_search_stage_does_not_run_when_parameters_missing():
    """When intent_parameters is empty, DeepSearchStage must not run."""
    workflow = MagicMock()
    stage = DeepSearchStage(workflow=workflow)

    ctx = _make_context(
        query="fix the login error",
        intent=IntentType.FIX_BUG,
        intent_parameters={},
    )

    await stage.execute(ctx)

    workflow.run.assert_not_called()
    assert ctx.early_exit is None


@pytest.mark.asyncio
async def test_response_generation_normal_path_unaffected():
    """The normal response path must work correctly when Deep Search is not used."""
    ctx = _make_context(
        query="find the login function",
        intent=IntentType.RETRIEVE,
    )
    ctx.early_exit = None
    ctx.deep_search_result = None
    ctx.analysis_result = {
        "analysis_status": "OK",
        "suggestion": "The login function is in auth/views.py.",
        "requirement": "Find the login function.",
    }
    ctx.triage_result = None

    stage = ResponseGenerationStage()
    await stage.execute(ctx)

    response = ctx.final_response
    assert response is not None
    # Deep Search was not used — root_cause_analysis must not be set.
    assert response.root_cause_analysis is None


def test_graph_records_template_field_without_fabricating_model_edge(graph):
    """The graph must not invent model-membership edges from template field refs."""
    template_refs = [
        node
        for node in graph.nodes.values()
        if node.kind == "template_attribute_reference"
    ]
    assert any(
        node.name == "appointment_date"
        and node.path == "templates/appointments.html"
        for node in template_refs
    )

    assert not any(
        edge.kind in {"belongs_to_model", "model_field"}
        and edge.source_path == "templates/appointments.html"
        for edge in graph.edges
    )
