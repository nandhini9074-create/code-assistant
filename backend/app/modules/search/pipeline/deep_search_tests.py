
from __future__ import annotations

import pytest

from app.modules.search.pipeline.dependency_graph import (
    DependencyGraphBuilder,
    build_dependency_graph,
)
from app.modules.search.pipeline.deep_search_explorer import (
    DeepSearchExplorer,
)
from app.modules.search.pipeline.deep_search_retriever import (
    DeepSearchRetriever,
    TargetedSearchRequest,
)
from app.modules.search.pipeline.deep_search_assessor import (
    DeepSearchAssessor,
)


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


# ---------------------------------------------------------------------------
# DependencyGraphBuilder tests
# ---------------------------------------------------------------------------

def test_graph_creates_file_and_symbol_nodes(graph):
    assert "file:app/routes.py" in graph.nodes
    assert "file:app/services.py" in graph.nodes

    route_id = "symbol:app/routes.py::appointment_route"
    service_id = "symbol:app/services.py::get_appointment"

    assert route_id in graph.nodes
    assert service_id in graph.nodes

    assert graph.nodes[route_id].kind == "function"
    assert graph.nodes[service_id].kind == "function"


def test_graph_resolves_import_and_cross_file_function_call(graph):
    import_edges = [
        edge
        for edge in graph.edges
        if edge.kind == "imports"
    ]

    call_edges = [
        edge
        for edge in graph.edges
        if edge.kind == "calls"
        and edge.evidence == "get_appointment"
    ]

    assert any(
        edge.source == "file:app/routes.py"
        and edge.target == "file:app/services.py"
        for edge in import_edges
    )

    assert any(
        edge.source == "symbol:app/routes.py::appointment_route"
        and edge.target == "symbol:app/services.py::get_appointment"
        for edge in call_edges
    )


def test_graph_records_template_attribute_without_guessing_model(graph):
    template_references = [
        node
        for node in graph.nodes.values()
        if node.kind == "template_attribute_reference"
    ]

    assert any(
        node.name == "appointment_date"
        and node.path == "templates/appointments.html"
        for node in template_references
    )

    # A template field reference must not automatically establish that the
    # referenced field belongs to a particular Python model.
    assert not any(
        edge.kind in {"belongs_to_model", "model_field"}
        and edge.source_path == "templates/appointments.html"
        for edge in graph.edges
    )


def test_graph_records_unparseable_python_as_unresolved():
    graph = build_dependency_graph({
        "app/broken.py": "def broken(:\n    pass\n",
    })

    assert any(
        item.path == "app/broken.py"
        and item.kind == "parse_error"
        for item in graph.unresolved
    )


def test_graph_rejects_parent_directory_paths():
    builder = DependencyGraphBuilder()

    with pytest.raises(ValueError):
        builder.build({
            "../outside.py": "print('outside')",
        })


def test_graph_respects_file_limit():
    builder = DependencyGraphBuilder(max_files=2)

    graph = builder.build({
        "app/a.py": "def a():\n    pass\n",
        "app/b.py": "def b():\n    pass\n",
        "app/c.py": "def c():\n    pass\n",
    })

    assert graph.metadata["truncated_files"] is True
    assert graph.metadata["source_file_count"] == 2
    assert "file:app/c.py" not in graph.nodes


# ---------------------------------------------------------------------------
# DeepSearchExplorer tests
# ---------------------------------------------------------------------------

def test_explorer_finds_related_cross_file_targets(graph):
    explorer = DeepSearchExplorer(
        max_depth=3,
        max_targets=12,
    )

    result = explorer.explore(
        query="appointment_route",
        graph=graph,
    )

    assert result.targets

    selected_ids = {
        target.node_id
        for target in result.targets
    }

    assert "symbol:app/routes.py::appointment_route" in selected_ids
    assert "symbol:app/services.py::get_appointment" in selected_ids


def test_explorer_returns_no_guessed_targets_for_unmatched_query(graph):
    explorer = DeepSearchExplorer()

    result = explorer.explore(
        query="unrelated unknown_identifier_xyz",
        graph=graph,
    )

    assert result.targets == ()
    assert "No graph node matched" in result.reason


def test_explorer_respects_target_limit(graph):
    explorer = DeepSearchExplorer(
        max_depth=5,
        max_targets=1,
    )

    result = explorer.explore(
        query="appointment_route",
        graph=graph,
    )

    assert len(result.targets) <= 1


def test_explorer_handles_empty_query(graph):
    result = DeepSearchExplorer().explore(
        query="",
        graph=graph,
    )

    assert result.targets == ()
    assert result.reason == "The bug query is empty."


# ---------------------------------------------------------------------------
# DeepSearchRetriever tests
# ---------------------------------------------------------------------------

def test_retriever_uses_resolved_collection_and_target_paths(
    retrieval_state,
):
    captured_requests: list[TargetedSearchRequest] = []

    def fake_search_adapter(request: TargetedSearchRequest):
        captured_requests.append(request)

        return [
            {
                "path": "app/services.py",
                "content": (
                    "def get_appointment():\n"
                    "    return None\n"
                ),
                "line_start": 1,
                "line_end": 2,
            },
            {
                # Must be rejected: this path is outside the requested scope.
                "path": "app/unrelated.py",
                "content": "def unrelated():\n    pass\n",
                "line_start": 1,
                "line_end": 2,
            },
        ]

    retriever = DeepSearchRetriever(
        search_adapter=fake_search_adapter,
    )

    result = retriever.retrieve(
        query="appointment error",
        targets=[
            {
                "path": "app/services.py",
                "name": "get_appointment",
                "kind": "function",
            }
        ],
        state=retrieval_state,
    )

    assert len(captured_requests) == 1

    request = captured_requests[0]
    assert request.collection_name == "repo_owner_hospital"
    assert request.repo_name == "owner_hospital"
    assert request.target_paths == ("app/services.py",)

    assert result["status"] == "SUCCESS"
    assert result["retrieved_count"] == 1
    assert result["retrieved_chunks"][0]["path"] == "app/services.py"
    assert result["missing_targets"] == ()


def test_retriever_does_not_search_without_resolved_collection():
    adapter_called = False

    def fake_search_adapter(request):
        nonlocal adapter_called
        adapter_called = True
        return []

    retriever = DeepSearchRetriever(
        search_adapter=fake_search_adapter,
    )

    result = retriever.retrieve(
        query="appointment error",
        targets=["app/services.py"],
        state={"repo_name": "owner_hospital"},
    )

    assert result["status"] == "UNAVAILABLE"
    assert adapter_called is False


def test_retriever_returns_unavailable_without_adapter(
    retrieval_state,
):
    retriever = DeepSearchRetriever()

    result = retriever.retrieve(
        query="appointment error",
        targets=["app/services.py"],
        state=retrieval_state,
    )

    assert result["status"] == "UNAVAILABLE"
    assert result["retrieved_count"] == 0


def test_retriever_rejects_unrelated_chunks(
    retrieval_state,
):
    retriever = DeepSearchRetriever(
        search_adapter=lambda request: [
            {
                "path": "app/other.py",
                "content": "def other():\n    pass\n",
            }
        ],
    )

    result = retriever.retrieve(
        query="appointment error",
        targets=["app/services.py"],
        state=retrieval_state,
    )

    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["retrieved_chunks"] == []
    assert result["missing_targets"] == ("app/services.py",)


# ---------------------------------------------------------------------------
# DeepSearchAssessor tests
# ---------------------------------------------------------------------------

def test_assessor_accepts_diagnosis_with_verifiable_source_evidence(
    retrieved_chunks,
):
    def fake_assessment_adapter(payload):
        return {
            "is_sufficient": True,
            "diagnosis": (
                "The retrieved function currently returns None; "
                "additional call-site evidence is needed before determining "
                "whether this explains the reported runtime failure."
            ),
            "confidence": 0.85,
            "evidence": [
                {
                    "path": "app/services.py",
                    "quote": "return None",
                    "claim": (
                        "The function returns None in the retrieved source."
                    ),
                    "line_start": 2,
                    "line_end": 2,
                }
            ],
            "follow_up_targets": [],
            "reason": "The cited behavior is visible in the retrieved source.",
        }

    assessor = DeepSearchAssessor(
        assessment_adapter=fake_assessment_adapter,
        min_confidence=0.55,
    )

    result = assessor.assess({
        "query": "Why does get_appointment return an empty value?",
        "retrieved_chunks": retrieved_chunks,
        "rounds": 0,
        "max_rounds": 3,
    })

    assert result["status"] == "complete"
    assert result["diagnosis"] is not None
    assert result["confidence"] == 0.85
    assert len(result["evidence"]) == 1
    assert result["evidence"][0]["quote"] == "return None"


def test_assessor_rejects_fabricated_evidence(retrieved_chunks):
    def fake_assessment_adapter(payload):
        return {
            "is_sufficient": True,
            "diagnosis": "The model adds appointment_date automatically.",
            "confidence": 0.99,
            "evidence": [
                {
                    "path": "app/services.py",
                    "quote": "appointment_date = None",
                    "claim": "The model defines this field.",
                }
            ],
            "follow_up_targets": [],
            "reason": "The adapter claims the diagnosis is supported.",
        }

    assessor = DeepSearchAssessor(
        assessment_adapter=fake_assessment_adapter,
    )

    result = assessor.assess({
        "query": "Appointment has no appointment_date attribute",
        "retrieved_chunks": retrieved_chunks,
        "rounds": 0,
        "max_rounds": 3,
    })

    assert result["status"] == "incomplete"
    assert result["diagnosis"] is None
    assert result["evidence"] == []


def test_assessor_requests_bounded_follow_up(graph, retrieved_chunks):
    def fake_assessment_adapter(payload):
        return {
            "is_sufficient": False,
            "diagnosis": None,
            "confidence": 0.25,
            "evidence": [],
            "follow_up_targets": [
                "file:app/models.py",
                "file:not_in_the_graph.py",
            ],
            "follow_up_query": (
                "Inspect the appointment model to verify the available fields."
            ),
            "reason": "The current code does not establish the object contract.",
        }

    assessor = DeepSearchAssessor(
        assessment_adapter=fake_assessment_adapter,
        max_rounds=3,
    )

    result = assessor.assess({
        "query": "Appointment has no appointment_date attribute",
        "retrieved_chunks": retrieved_chunks,
        "dependency_graph": graph,
        "rounds": 0,
        "max_rounds": 3,
    })

    assert result["status"] == "running"
    assert result["diagnosis"] is None
    assert result["follow_up_targets"] == ["file:app/models.py"]
    assert result["follow_up_query"] is not None


def test_assessor_stops_when_round_limit_is_reached(
    graph,
    retrieved_chunks,
):
    def fake_assessment_adapter(payload):
        return {
            "is_sufficient": False,
            "diagnosis": None,
            "confidence": 0.3,
            "evidence": [],
            "follow_up_targets": ["file:app/models.py"],
            "follow_up_query": "Inspect the model.",
            "reason": "More evidence would be helpful.",
        }

    assessor = DeepSearchAssessor(
        assessment_adapter=fake_assessment_adapter,
        max_rounds=3,
    )

    result = assessor.assess({
        "query": "Appointment field mismatch",
        "retrieved_chunks": retrieved_chunks,
        "dependency_graph": graph,
        "rounds": 2,
        "max_rounds": 3,
    })

    assert result["status"] == "incomplete"
    assert result["diagnosis"] is None
    assert result["follow_up_targets"] == []


def test_assessor_does_not_claim_success_without_adapter(
    retrieved_chunks,
):
    assessor = DeepSearchAssessor()

    result = assessor.assess({
        "query": "Investigate appointment field mismatch",
        "retrieved_chunks": retrieved_chunks,
    })

    assert result["status"] == "incomplete"
    assert result["diagnosis"] is None


def test_assessor_returns_unavailable_when_adapter_fails(
    retrieved_chunks,
):
    def failing_adapter(payload):
        raise RuntimeError("Simulated analysis failure")

    assessor = DeepSearchAssessor(
        assessment_adapter=failing_adapter,
    )

    result = assessor.assess({
        "query": "Investigate appointment field mismatch",
        "retrieved_chunks": retrieved_chunks,
    })

    assert result["status"] == "unavailable"
    assert result["diagnosis"] is None
