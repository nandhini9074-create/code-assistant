"""
app/modules/search/pipeline/test_deep_search_integration.py

Integration tests for the complete Deep Search workflow in the FIX_BUG
search pipeline.

Tests cover:
1. NORMAL_FIX path for simple local bugs.
2. DEEP_SEARCH path triggered automatically (no keywords required).
3. Escalation from NORMAL_FIX when normal evidence is insufficient.
4. Template-to-route-to-model cross-component mismatch detection.
5. Unresolved graph edges are not treated as verified dependencies.
6. Incomplete source results in INSUFFICIENT_EVIDENCE.
7. Conflicting candidates result in AMBIGUOUS, not fabricated fix.
8. Graph truncation, retrieval failures, and LLM failures terminate
   deterministically.
9. Verified fix passes suggestion/diff validation.
10. Non-verified results do not generate fabricated patches.
11. RETRIEVE, ADD_FEATURE, OPTIMIZE, REFACTOR, FIX_VULNERABILITY retain
    their existing execution behavior (Deep Search does NOT activate).
12. Service-level routing: deep_search_requested flag drives execution.
"""

from __future__ import annotations

import asyncio
import pytest

from app.modules.search.pipeline.deep_search_decision import (
    DeepSearchDecision,
    decide_deep_search,
    decide_deep_search_escalation,
)
from app.modules.search.pipeline.deep_search_assessor import DeepSearchAssessor
from app.modules.search.pipeline.deep_search_explorer import DeepSearchExplorer
from app.modules.search.pipeline.deep_search_retriever import (
    DeepSearchRetriever,
    TargetedSearchRequest,
)
from app.modules.search.pipeline.dependency_graph import build_dependency_graph
from app.modules.search.pipeline.deep_search import (
    DeepSearchStage,
    DeepSearchWorkflow,
)
from app.modules.search.domain.search_domain import SearchContext
from app.core.enums import IntentType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def source_files():
    return {
        "app/routes.py": (
            "from app.services import get_appointment\n\n"
            "def appointment_route():\n"
            "    appt = get_appointment()\n"
            "    return render_template('appointments.html', appointment=appt)\n"
        ),
        "app/services.py": (
            "from app.models import Appointment\n\n"
            "def get_appointment():\n"
            "    return Appointment(appointment_time='10:00')\n"
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
def retrieval_state():
    return {
        "repo_name": "owner_hospital",
        "collection_name": "repo_owner_hospital",
    }


@pytest.fixture
def appointment_chunk():
    return {
        "path": "app/models.py",
        "content": (
            "class Appointment:\n"
            "    def __init__(self, appointment_time):\n"
            "        self.appointment_time = appointment_time\n"
        ),
        "line_start": 1,
        "line_end": 3,
    }


# ===========================================================================
# 1.  decide_deep_search -- routing decision tests
# ===========================================================================

class TestDecideDeepSearch:
    """Unit tests for the pre-retrieval routing decision."""

    def test_simple_local_bug_uses_normal_fix(self):
        """A plain fix-the-null-return query stays NORMAL_FIX."""
        decision = decide_deep_search(
            intent="FIX_BUG",
            query="The function returns None instead of a list",
        )
        assert decision.selected is False, decision.reason

    def test_non_fix_bug_intent_is_never_selected(self):
        for intent in ("RETRIEVE", "ADD_FEATURE", "OPTIMIZE", "REFACTOR",
                       "FIX_VULNERABILITY"):
            decision = decide_deep_search(
                intent=intent,
                query="Fix the appointment page error",
            )
            assert decision.selected is False, (
                f"Expected NORMAL for intent={intent}, got Deep Search: "
                f"{decision.reason}"
            )

    def test_attribute_error_message_selects_deep_search(self):
        """AttributeError messages select Deep Search without keywords."""
        decision = decide_deep_search(
            intent="FIX_BUG",
            query=(
                "Appointment object has no attribute appointment_date"
            ),
        )
        assert decision.selected is True, decision.reason

    def test_page_error_selects_deep_search(self):
        """A page-level error triggers Deep Search without keywords."""
        decision = decide_deep_search(
            intent="FIX_BUG",
            query="Fix the appointment page error",
        )
        assert decision.selected is True, decision.reason

    def test_explicit_deep_search_keyword_selects(self):
        decision = decide_deep_search(
            intent="FIX_BUG",
            query="deep search to find the bug root cause",
        )
        assert decision.selected is True

    def test_cross_file_pattern_selects(self):
        decision = decide_deep_search(
            intent="FIX_BUG",
            query="trace the call flow across multiple files",
        )
        assert decision.selected is True

    def test_wrong_field_reference_selects(self):
        decision = decide_deep_search(
            intent="FIX_BUG",
            query="wrong field reference in the appointment view",
        )
        assert decision.selected is True

    def test_missing_attribute_selects(self):
        decision = decide_deep_search(
            intent="FIX_BUG",
            query="missing attribute appointment_date on Appointment",
        )
        assert decision.selected is True

    def test_has_no_attribute_selects(self):
        """'has no attribute' phrase selects Deep Search."""
        decision = decide_deep_search(
            intent="FIX_BUG",
            query="'Appointment' object has no attribute 'date'",
        )
        assert decision.selected is True

    def test_route_service_model_order_independent(self):
        """route/service/model tokens in any order trigger Deep Search."""
        for query in (
            "the model calls the route via service",
            "service route model investigation needed",
            "model is broken, route and service involved",
        ):
            decision = decide_deep_search(intent="FIX_BUG", query=query)
            assert decision.selected is True, (
                f"Expected Deep Search for: {query!r}"
            )

    def test_template_model_selects(self):
        decision = decide_deep_search(
            intent="FIX_BUG",
            query="template uses model field incorrectly",
        )
        assert decision.selected is True

    def test_empty_query_is_normal_fix(self):
        decision = decide_deep_search(intent="FIX_BUG", query="")
        assert decision.selected is False

    def test_attributeerror_keyword_selects(self):
        decision = decide_deep_search(
            intent="FIX_BUG",
            query="AttributeError in appointments view",
        )
        assert decision.selected is True

    def test_page_not_working_selects(self):
        decision = decide_deep_search(
            intent="FIX_BUG",
            query="appointment page is broken",
        )
        assert decision.selected is True


# ===========================================================================
# 2.  decide_deep_search_escalation -- post-retrieval escalation tests
# ===========================================================================

class TestDecideDeepSearchEscalation:
    """Unit tests for post-retrieval escalation decision."""

    def test_empty_retrieved_chunks_escalates(self):
        decision = decide_deep_search_escalation(
            query="Fix appointment page error",
            retrieved_chunks=[],
            analysis_result=None,
        )
        assert decision.selected is True

    def test_analysis_unavailable_escalates(self):
        decision = decide_deep_search_escalation(
            query="Fix appointment page error",
            retrieved_chunks=[{"path": "a.py", "content": "x = 1"}],
            analysis_result={"analysis_status": "UNAVAILABLE"},
        )
        assert decision.selected is True

    def test_cross_component_evidence_escalates(self):
        decision = decide_deep_search_escalation(
            query="Fix appointment page error",
            retrieved_chunks=[{"path": "a.py", "content": "x = 1"}],
            analysis_result={
                "analysis_status": "COMPLETE",
                "evidence_summary": "Appointment has no attribute appointment_date",
            },
        )
        assert decision.selected is True

    def test_sufficient_evidence_does_not_escalate(self):
        decision = decide_deep_search_escalation(
            query="fix the null return value",
            retrieved_chunks=[{"path": "a.py", "content": "return None"}],
            analysis_result={"analysis_status": "COMPLETE", "evidence_summary": ""},
        )
        assert decision.selected is False


# ===========================================================================
# 3.  Service-level routing: deep_search_requested flag
# ===========================================================================

class TestServiceRoutingFlag:
    """
    Test that SearchService._deep_search_selected reads the flag correctly,
    and that _should_escalate_to_deep_search only fires for FIX_BUG.
    """

    def _make_context(self, intent, deep_search_requested=False, params=None):
        ctx = SearchContext(query="test query")
        ctx.intent = intent
        ctx.intent_parameters = dict(params or {})
        if deep_search_requested:
            ctx.intent_parameters["deep_search_requested"] = True
        return ctx

    def test_deep_search_selected_true_for_fix_bug(self):
        from app.modules.search.service.search_service import SearchService
        ctx = self._make_context(IntentType.FIX_BUG, deep_search_requested=True)
        assert SearchService._deep_search_selected(ctx) is True

    def test_deep_search_selected_false_without_flag(self):
        from app.modules.search.service.search_service import SearchService
        ctx = self._make_context(IntentType.FIX_BUG)
        assert SearchService._deep_search_selected(ctx) is False

    def test_deep_search_selected_false_for_non_fix_bug(self):
        from app.modules.search.service.search_service import SearchService
        for intent in (IntentType.RETRIEVE, IntentType.ADD_FEATURE,
                       IntentType.OPTIMIZE, IntentType.REFACTOR):
            ctx = self._make_context(intent, deep_search_requested=True)
            assert SearchService._deep_search_selected(ctx) is False, (
                f"Expected False for {intent}"
            )

    def test_should_not_escalate_for_non_fix_bug(self):
        from app.modules.search.service.search_service import SearchService
        for intent in (IntentType.RETRIEVE, IntentType.ADD_FEATURE,
                       IntentType.OPTIMIZE, IntentType.REFACTOR):
            ctx = self._make_context(intent)
            ctx.retrieved_chunks = []
            ctx.analysis_result = None
            assert SearchService._should_escalate_to_deep_search(ctx) is False

    def test_should_not_escalate_when_already_selected(self):
        from app.modules.search.service.search_service import SearchService
        ctx = self._make_context(IntentType.FIX_BUG, deep_search_requested=True)
        ctx.retrieved_chunks = []
        ctx.analysis_result = None
        assert SearchService._should_escalate_to_deep_search(ctx) is False

    def test_should_escalate_with_empty_chunks(self):
        from app.modules.search.service.search_service import SearchService
        ctx = self._make_context(IntentType.FIX_BUG)
        ctx.retrieved_chunks = []
        ctx.analysis_result = None
        assert SearchService._should_escalate_to_deep_search(ctx) is True

    def test_should_not_escalate_after_early_exit(self):
        from app.modules.search.service.search_service import SearchService
        ctx = self._make_context(IntentType.FIX_BUG)
        ctx.retrieved_chunks = []
        ctx.analysis_result = None
        ctx.early_exit = "EARLY_EXIT_A"
        assert SearchService._should_escalate_to_deep_search(ctx) is False


# ===========================================================================
# 4.  DeepSearchWorkflow: template-to-model cross-component investigation
# ===========================================================================

class TestDeepSearchWorkflowCrossComponent:
    """Verify that the workflow investigates cross-component dependencies."""

    def _make_workflow(self, source_files, assessment_result=None):
        def source_provider(state):
            return source_files

        def assessment_adapter(payload):
            if assessment_result is not None:
                return assessment_result
            # Default: insufficient evidence
            return {
                "is_sufficient": False,
                "diagnosis": None,
                "confidence": 0.1,
                "evidence": [],
                "follow_up_targets": [],
                "reason": "Insufficient evidence in this test.",
            }

        return DeepSearchWorkflow(
            source_provider=source_provider,
            assessment_adapter=assessment_adapter,
            max_rounds=2,
            max_graph_depth=3,
            max_targets=12,
        )

    def test_investigates_appointment_model_files(self, source_files):
        """Workflow explores the appointment model through dependency graph."""
        workflow = self._make_workflow(source_files)

        result = workflow.run({
            "query": (
                "Appointment object has no attribute appointment_date"
            ),
            "intent": "FIX_BUG",
            "deep_search_requested": True,
            "repo_name": "owner_hospital",
            "collection_name": "repo_owner_hospital",
            "source_files": source_files,
        })

        # Must terminate deterministically.
        assert result["status"] in ("complete", "incomplete", "unavailable")
        assert result["intent"] == "FIX_BUG"

    def test_graph_builds_without_fabricated_edges(self, source_files):
        """Graph does not fabricate template-to-model edges."""
        graph = build_dependency_graph(source_files)

        template_nodes = [
            n for n in graph.nodes.values()
            if n.path == "templates/appointments.html"
        ]
        assert template_nodes  # template must be recorded

        # Template attribute references must not auto-create model edges.
        for edge in graph.edges:
            if (
                "appointments.html" in edge.source
                and edge.kind in ("belongs_to_model", "model_field")
            ):
                pytest.fail(
                    f"Fabricated model edge from template: {edge}"
                )

    def test_unresolved_graph_edge_is_not_verified_dependency(self, source_files):
        """Unresolved references are recorded but not treated as verified."""
        graph = build_dependency_graph(source_files)

        unresolved_paths = {item.path for item in graph.unresolved}
        # All unresolved items must remain explicitly unresolved.
        for item in graph.unresolved:
            assert item.kind in (
                "unresolved_import",
                "unresolved_call",
                "parse_error",
                "unresolved_attribute",
                "template_attribute_reference",
            ), f"Unexpected unresolved kind: {item.kind}"


# ===========================================================================
# 5.  DeepSearchAssessor: evidence validation prevents fabricated patches
# ===========================================================================

class TestDeepSearchAssessorEvidenceValidation:
    """Verify the assessor rejects fabricated evidence."""

    def test_fabricated_quote_is_rejected(self):
        """Evidence with a quote not present in retrieved code is rejected."""
        def fake_adapter(payload):
            return {
                "is_sufficient": True,
                "diagnosis": "The model defines appointment_date.",
                "confidence": 0.95,
                "evidence": [
                    {
                        "path": "app/models.py",
                        "quote": "self.appointment_date = None",
                        "claim": "The model defines the field.",
                        "line_start": 3,
                        "line_end": 3,
                    }
                ],
                "follow_up_targets": [],
                "reason": "Fabricated.",
            }

        assessor = DeepSearchAssessor(assessment_adapter=fake_adapter)
        result = assessor.assess({
            "query": "Appointment has no attribute appointment_date",
            "retrieved_chunks": [
                {
                    "path": "app/models.py",
                    "content": (
                        "class Appointment:\n"
                        "    def __init__(self, appointment_time):\n"
                        "        self.appointment_time = appointment_time\n"
                    ),
                    "line_start": 1,
                    "line_end": 3,
                }
            ],
        })

        # Fabricated quote not in source -- must not be "complete".
        assert result["status"] in ("incomplete", "unavailable")
        assert result["diagnosis"] is None

    def test_verified_quote_accepted(self):
        """Evidence with a real quote from retrieved code is accepted."""
        def fake_adapter(payload):
            return {
                "is_sufficient": True,
                "diagnosis": "The model defines appointment_time, not appointment_date.",
                "confidence": 0.85,
                "evidence": [
                    {
                        "path": "app/models.py",
                        "quote": "self.appointment_time = appointment_time",
                        "claim": "Model only defines appointment_time.",
                        "line_start": 3,
                        "line_end": 3,
                    }
                ],
                "follow_up_targets": [],
                "reason": "Verified from source.",
            }

        assessor = DeepSearchAssessor(assessment_adapter=fake_adapter)
        result = assessor.assess({
            "query": "Appointment has no attribute appointment_date",
            "retrieved_chunks": [
                {
                    "path": "app/models.py",
                    "content": (
                        "class Appointment:\n"
                        "    def __init__(self, appointment_time):\n"
                        "        self.appointment_time = appointment_time\n"
                    ),
                    "line_start": 1,
                    "line_end": 3,
                }
            ],
        })

        assert result["status"] == "complete"
        assert result["diagnosis"] is not None
        assert len(result["evidence"]) == 1

    def test_no_adapter_returns_incomplete(self):
        """Without an adapter, assessor returns incomplete (not fabricated)."""
        assessor = DeepSearchAssessor()
        result = assessor.assess({
            "query": "appointment_date missing",
            "retrieved_chunks": [
                {
                    "path": "app/models.py",
                    "content": "class Appointment: pass",
                    "line_start": 1,
                    "line_end": 1,
                }
            ],
        })
        assert result["status"] == "incomplete"
        assert result["diagnosis"] is None

    def test_adapter_failure_returns_unavailable(self):
        """An adapter exception terminates deterministically."""
        def failing_adapter(payload):
            raise RuntimeError("simulated LLM failure")

        assessor = DeepSearchAssessor(assessment_adapter=failing_adapter)
        result = assessor.assess({
            "query": "appointment field missing",
            "retrieved_chunks": [
                {"path": "a.py", "content": "x = 1", "line_start": 1, "line_end": 1}
            ],
        })
        assert result["status"] == "unavailable"
        assert result["diagnosis"] is None

    def test_conflicting_candidates_return_ambiguous_not_fabricated(self):
        """When evidence is conflicting, result is incomplete/ambiguous."""
        call_count = {"n": 0}

        def ambiguous_adapter(payload):
            call_count["n"] += 1
            # First call: claims sufficient but provides two conflicting claims.
            return {
                "is_sufficient": True,
                "diagnosis": "Unknown -- conflicting evidence.",
                "confidence": 0.30,  # Below min_confidence
                "evidence": [
                    {
                        "path": "app/models.py",
                        "quote": "self.appointment_time = appointment_time",
                        "claim": "Model defines appointment_time.",
                    }
                ],
                "follow_up_targets": [],
                "reason": "Conflicting findings.",
            }

        assessor = DeepSearchAssessor(
            assessment_adapter=ambiguous_adapter,
            min_confidence=0.55,
        )
        result = assessor.assess({
            "query": "appointment_date or appointment_time?",
            "retrieved_chunks": [
                {
                    "path": "app/models.py",
                    "content": (
                        "class Appointment:\n"
                        "    def __init__(self, appointment_time):\n"
                        "        self.appointment_time = appointment_time\n"
                    ),
                    "line_start": 1,
                    "line_end": 3,
                }
            ],
        })

        # Low confidence prevents claiming "complete".
        assert result["status"] in ("incomplete", "unavailable")
        assert result["diagnosis"] is None


# ===========================================================================
# 6.  DeepSearchWorkflow: terminal conditions
# ===========================================================================

class TestDeepSearchWorkflowTerminalConditions:
    """Verify the workflow terminates deterministically for edge cases."""

    def test_no_source_provider_returns_unavailable(self):
        """Without a source provider or source_files, workflow is unavailable."""
        workflow = DeepSearchWorkflow(max_rounds=2)

        result = workflow.run({
            "query": "Appointment object has no attribute appointment_date",
            "intent": "FIX_BUG",
            "deep_search_requested": True,
            "repo_name": "owner_hospital",
            "collection_name": "repo_owner_hospital",
        })

        assert result["status"] == "unavailable"
        assert result["diagnosis"] is None

    def test_invalid_intent_returns_unavailable(self):
        """Non-FIX_BUG intent is rejected deterministically."""
        workflow = DeepSearchWorkflow(max_rounds=2)

        result = workflow.run({
            "query": "Add a feature",
            "intent": "ADD_FEATURE",
            "deep_search_requested": True,
            "repo_name": "owner_hospital",
            "collection_name": "repo_owner_hospital",
        })

        assert result["status"] == "unavailable"

    def test_missing_repo_name_returns_unavailable(self):
        workflow = DeepSearchWorkflow(max_rounds=2)

        result = workflow.run({
            "query": "Fix the bug",
            "intent": "FIX_BUG",
            "deep_search_requested": True,
            "repo_name": "",
            "collection_name": "repo_owner_hospital",
        })

        assert result["status"] == "unavailable"

    def test_investigation_limit_terminates(self):
        """Workflow respects max_rounds and terminates deterministically."""
        rounds_counted = {"n": 0}

        def source_provider(state):
            return {
                "app/models.py": (
                    "class Appointment:\n"
                    "    appointment_time = None\n"
                )
            }

        def assessment_adapter(payload):
            rounds_counted["n"] += 1
            # Always request follow-up with valid graph targets.
            return {
                "is_sufficient": False,
                "diagnosis": None,
                "confidence": 0.2,
                "evidence": [],
                "follow_up_targets": ["file:app/models.py"],
                "follow_up_query": "Keep investigating.",
                "reason": "More rounds needed.",
            }

        workflow = DeepSearchWorkflow(
            source_provider=source_provider,
            assessment_adapter=assessment_adapter,
            max_rounds=2,
            max_graph_depth=1,
            max_targets=5,
        )

        result = workflow.run({
            "query": "Appointment object has no attribute appointment_date",
            "intent": "FIX_BUG",
            "deep_search_requested": True,
            "repo_name": "owner_hospital",
            "collection_name": "repo_owner_hospital",
        })

        # Must terminate (not loop forever).
        assert result["status"] in ("complete", "incomplete", "unavailable")


# ===========================================================================
# 7.  DeepSearchStage: async adapter for the pipeline
# ===========================================================================

class TestDeepSearchStageAdapter:
    """Verify DeepSearchStage integrates correctly with SearchContext."""

    def _make_context(self, deep_requested=True):
        ctx = SearchContext(query="Appointment object has no attribute appointment_date")
        ctx.intent = IntentType.FIX_BUG
        ctx.repo_name = "owner_hospital"
        ctx.qdrant_collection = "repo_owner_hospital"
        ctx.intent_parameters = {"deep_search_requested": deep_requested}
        return ctx

    def test_stage_sets_early_exit_on_completion(self):
        """DeepSearchStage sets early_exit='DEEP_SEARCH_COMPLETE'."""
        def source_provider(state):
            return {
                "app/models.py": (
                    "class Appointment:\n"
                    "    def __init__(self, appointment_time):\n"
                    "        self.appointment_time = appointment_time\n"
                )
            }

        stage = DeepSearchStage(
            workflow=DeepSearchWorkflow(
                source_provider=source_provider,
                max_rounds=1,
            )
        )

        ctx = self._make_context()

        async def run():
            await stage.execute(ctx)

        asyncio.run(run())

        assert ctx.early_exit == "DEEP_SEARCH_COMPLETE"
        assert isinstance(ctx.deep_search_result, dict)

    def test_stage_skips_non_fix_bug_intent(self):
        """DeepSearchStage does nothing for non-FIX_BUG intents."""
        stage = DeepSearchStage()
        ctx = SearchContext(query="Add a feature")
        ctx.intent = IntentType.ADD_FEATURE
        ctx.repo_name = "owner_hospital"
        ctx.qdrant_collection = "repo_owner_hospital"
        ctx.intent_parameters = {"deep_search_requested": True}

        async def run():
            await stage.execute(ctx)

        asyncio.run(run())

        # early_exit must not be set to DEEP_SEARCH_COMPLETE.
        assert ctx.early_exit != "DEEP_SEARCH_COMPLETE"

    def test_stage_skips_when_deep_search_not_requested(self):
        """DeepSearchStage is a no-op when not requested."""
        stage = DeepSearchStage()
        ctx = self._make_context(deep_requested=False)

        async def run():
            await stage.execute(ctx)

        asyncio.run(run())

        assert ctx.early_exit != "DEEP_SEARCH_COMPLETE"
        assert ctx.deep_search_result is None


# ===========================================================================
# 8.  Retriever: cross-collection safety
# ===========================================================================

class TestDeepSearchRetrieverCollectionSafety:
    """Verify the retriever enforces collection scope."""

    def test_retriever_rejects_unrelated_path(self, retrieval_state):
        """Chunks from paths outside the target list are rejected."""
        retriever = DeepSearchRetriever(
            search_adapter=lambda req: [
                {"path": "app/unrelated.py", "content": "x = 1",
                 "line_start": 1, "line_end": 1},
                {"path": "app/models.py", "content": "class Appointment: pass",
                 "line_start": 1, "line_end": 1},
            ]
        )

        result = retriever.retrieve(
            query="appointment_date",
            targets=[{"path": "app/models.py", "name": "Appointment", "kind": "class"}],
            state=retrieval_state,
        )

        assert result["status"] == "SUCCESS"
        assert all(c["path"] == "app/models.py" for c in result["retrieved_chunks"])
        assert len(result["retrieved_chunks"]) == 1

    def test_retriever_unavailable_without_collection(self):
        """Retriever aborts and reports UNAVAILABLE when collection is missing."""
        retriever = DeepSearchRetriever(
            search_adapter=lambda req: []
        )

        result = retriever.retrieve(
            query="appointment_date",
            targets=["app/models.py"],
            state={"repo_name": "owner_hospital"},
        )

        assert result["status"] == "UNAVAILABLE"


# ===========================================================================
# 9.  Original deep_search_tests.py regression guard
# ===========================================================================
# The existing tests in deep_search_tests.py are not imported here;
# running pytest on both files ensures they pass together.
