
"""
RepoLens Deep Search workflow.

Location:
    app/modules/search/pipeline/deep_search.py

Execution:
    validate -> build dependency graph -> explore -> targeted retrieval
    -> assess evidence -> bounded follow-up or terminal result

Design:
    - FIX_BUG only.
    - No repository writes.
    - No new Qdrant client.
    - No unbounded investigation loop.
    - No successful diagnosis without verified source evidence.
    - Normal search is not executed by this workflow.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Optional, TypedDict

from langgraph.graph import END, StateGraph

from app.modules.search.pipeline.dependency_graph import (
    DependencyGraph,
    build_dependency_graph,
)
from app.modules.search.pipeline.deep_search_assessor import (
    DeepSearchAssessor,
)
from app.modules.search.pipeline.deep_search_explorer import (
    DeepSearchExplorer,
)
from app.modules.search.pipeline.deep_search_retriever import (
    DeepSearchRetriever,
)


DEFAULT_MAX_ROUNDS = 3
DEFAULT_MAX_GRAPH_DEPTH = 3
DEFAULT_MAX_TARGETS = 12


class DeepSearchState(TypedDict, total=False):
    query: str
    intent: str
    deep_search_requested: bool

    repo_name: str
    collection_name: str
    resolved_collection: str
    selected_collection: str

    source_type: str
    source_location: str

    status: str
    error: Optional[str]

    dependency_graph: DependencyGraph
    graph_metadata: dict[str, Any]
    unresolved_references: list[dict[str, Any]]

    targets: list[Any]
    next_targets: list[str]
    seen_target_ids: list[str]

    retrieved_chunks: list[dict[str, Any]]
    missing_targets: list[str]
    retrieval_status: str

    retrieval_query: str
    rounds: int
    max_rounds: int

    assessment: dict[str, Any]
    assessment_status: str
    diagnosis: Optional[str]
    confidence: float
    evidence: list[dict[str, Any]]
    reason: str

    final_result: dict[str, Any]


# The provider must return source text from the requested repository only.
# It must use an existing, approved read-only source-access mechanism.
SourceProvider = Callable[
    [Mapping[str, Any]],
    Mapping[str, str],
]


class DeepSearchWorkflow:
    """
    Bounded LangGraph workflow for cross-file bug investigation.

    Dependencies are injected so the workflow does not assume the signatures
    of RepoLens's existing hybrid-search service or LLM service.
    """

    def __init__(
        self,
        *,
        source_provider: Optional[SourceProvider] = None,
        search_adapter: Optional[Callable] = None,
        assessment_adapter: Optional[Callable] = None,
        explorer: Optional[DeepSearchExplorer] = None,
        retriever: Optional[DeepSearchRetriever] = None,
        assessor: Optional[DeepSearchAssessor] = None,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
        max_graph_depth: int = DEFAULT_MAX_GRAPH_DEPTH,
        max_targets: int = DEFAULT_MAX_TARGETS,
    ) -> None:
        if max_rounds <= 0:
            raise ValueError("max_rounds must be positive.")

        if max_graph_depth < 0:
            raise ValueError("max_graph_depth cannot be negative.")

        if max_targets <= 0:
            raise ValueError("max_targets must be positive.")

        self.source_provider = source_provider
        self.max_rounds = max_rounds

        self.explorer = explorer or DeepSearchExplorer(
            max_depth=max_graph_depth,
            max_targets=max_targets,
        )

        self.retriever = retriever or DeepSearchRetriever(
            search_adapter=search_adapter,
            max_targets=max_targets,
        )

        self.assessor = assessor or DeepSearchAssessor(
            assessment_adapter=assessment_adapter,
            max_rounds=max_rounds,
        )

        self.app = self._build_graph()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(
        self,
        initial_state: Mapping[str, Any],
    ) -> dict[str, Any]:
        """
        Run Deep Search and return its explicit terminal result.

        Required input:
            query
            intent == "FIX_BUG"
            deep_search_requested == True
            repo_name
            resolved collection name

        Optional:
            source_files - provided by a trusted upstream read-only provider.
            Supplying this is useful for tests and controlled integrations.
        """
        state = dict(initial_state)

        state.setdefault("rounds", 0)
        state.setdefault("max_rounds", self.max_rounds)
        state.setdefault("targets", [])
        state.setdefault("next_targets", [])
        state.setdefault("seen_target_ids", [])
        state.setdefault("retrieved_chunks", [])
        state.setdefault("missing_targets", [])
        state.setdefault("retrieval_query", state.get("query", ""))

        # This validation happens before the workflow accesses source or
        # invokes a search adapter.
        validation_error = self._validate_input(state)

        if validation_error:
            return self._terminal_result(
                status="unavailable",
                reason=validation_error,
            )

        try:
            completed = self.app.invoke(state)
        except Exception as exc:
            return self._terminal_result(
                status="unavailable",
                reason=(
                    "Deep Search workflow execution failed "
                    f"({type(exc).__name__})."
                ),
            )

        final_result = completed.get("final_result")

        if isinstance(final_result, Mapping):
            return dict(final_result)

        return self._terminal_result(
            status="unavailable",
            reason="The workflow ended without a final result.",
        )

    @staticmethod
    def _validate_input(
        state: Mapping[str, Any],
    ) -> Optional[str]:
        query = state.get("query")

        if not isinstance(query, str) or not query.strip():
            return "The original bug query is missing."

        intent = str(state.get("intent", "")).strip().upper()

        if intent != "FIX_BUG":
            return "Deep Search only supports the FIX_BUG intent."

        if state.get("deep_search_requested") is not True:
            return "The Deep Search decision did not select this workflow."

        repo_name = state.get("repo_name")

        if not isinstance(repo_name, str) or not repo_name.strip():
            return "The selected repository identity is missing."

        collection_name = (
            state.get("collection_name")
            or state.get("resolved_collection")
            or state.get("selected_collection")
            or DeepSearchWorkflow._collection_from_selection(
                state.get("collection_selection")
            )
        )

        if not isinstance(collection_name, str) or not collection_name.strip():
            return (
                "The resolved repository collection is missing. "
                "Use the existing collection-selection stage before retrieval."
            )

        return None

    # ------------------------------------------------------------------
    # LangGraph construction
    # ------------------------------------------------------------------

    def _build_graph(self):
        graph = StateGraph(DeepSearchState)

        graph.add_node("build_dependency_graph", self._build_dependency_graph)
        graph.add_node("explore", self._explore)
        graph.add_node("retrieve", self._retrieve)
        graph.add_node("assess", self._assess)
        graph.add_node("finalize", self._finalize)

        graph.set_entry_point("build_dependency_graph")

        graph.add_conditional_edges(
            "build_dependency_graph",
            self._after_graph_build,
            {
                "explore": "explore",
                "finalize": "finalize",
            },
        )

        graph.add_conditional_edges(
            "explore",
            self._after_explore,
            {
                "retrieve": "retrieve",
                "finalize": "finalize",
            },
        )

        graph.add_conditional_edges(
            "retrieve",
            self._after_retrieval,
            {
                "assess": "assess",
                "finalize": "finalize",
            },
        )

        graph.add_conditional_edges(
            "assess",
            self._after_assessment,
            {
                "explore": "explore",
                "finalize": "finalize",
            },
        )

        graph.add_edge("finalize", END)

        return graph.compile()

    # ------------------------------------------------------------------
    # Stage 1: build the graph from actual repository source
    # ------------------------------------------------------------------

    def _build_dependency_graph(
        self,
        state: DeepSearchState,
    ) -> dict[str, Any]:
        try:
            source_files = state.get("source_files")

            if source_files is None:
                if self.source_provider is None:
                    return {
                        "status": "unavailable",
                        "error": (
                            "No read-only repository source provider is "
                            "configured. The dependency graph cannot be "
                            "built safely."
                        ),
                    }

                source_files = self.source_provider(dict(state))

            if not isinstance(source_files, Mapping):
                return {
                    "status": "unavailable",
                    "error": (
                        "The source provider did not return a mapping of "
                        "repository-relative paths to source text."
                    ),
                }

            if not source_files:
                return {
                    "status": "incomplete",
                    "error": (
                        "The source provider returned no files. No dependency "
                        "graph can be built from an empty source snapshot."
                    ),
                }

            if not all(
                isinstance(path, str) and isinstance(source, str)
                for path, source in source_files.items()
            ):
                return {
                    "status": "unavailable",
                    "error": (
                        "Source files must map repository-relative paths "
                        "to source text strings."
                    ),
                }

            dependency_graph = build_dependency_graph(source_files)

            file_nodes = [
                node
                for node in dependency_graph.nodes.values()
                if node.kind == "file"
            ]

            if not file_nodes:
                return {
                    "status": "incomplete",
                    "error": (
                        "The supplied source could not produce any usable "
                        "file nodes."
                    ),
                    "dependency_graph": dependency_graph,
                }

            return {
                "status": "graph_ready",
                "dependency_graph": dependency_graph,
                "graph_metadata": dict(dependency_graph.metadata),
                "unresolved_references": [
                    {
                        "source": item.source,
                        "path": item.path,
                        "line": item.line,
                        "kind": item.kind,
                        "expression": item.expression,
                        "reason": item.reason,
                    }
                    for item in dependency_graph.unresolved
                ],
                "error": None,
            }

        except Exception as exc:
            return {
                "status": "unavailable",
                "error": (
                    "Dependency graph construction failed "
                    f"({type(exc).__name__})."
                ),
            }

    @staticmethod
    def _after_graph_build(
        state: DeepSearchState,
    ) -> str:
        if (
            state.get("status") == "graph_ready"
            and state.get("dependency_graph") is not None
        ):
            return "explore"

        return "finalize"

    # ------------------------------------------------------------------
    # Stage 2: identify graph targets
    # ------------------------------------------------------------------

    def _explore(
        self,
        state: DeepSearchState,
    ) -> dict[str, Any]:
        dependency_graph = state.get("dependency_graph")

        if not isinstance(dependency_graph, DependencyGraph):
            return {
                "status": "incomplete",
                "error": "The dependency graph is unavailable.",
                "targets": [],
            }

        query = (
            state.get("retrieval_query")
            or state.get("query")
            or ""
        )

        next_targets = state.get("next_targets") or None

        result = self.explorer.explore(
            query=query,
            graph=dependency_graph,
            initial_targets=next_targets,
            previous_targets=state.get("seen_target_ids", []),
        )

        if not result.targets:
            return {
                "status": "incomplete",
                "targets": [],
                "exploration_reason": result.reason,
                "error": (
                    "No new verifiable investigation targets were identified. "
                    + result.reason
                ),
            }

        seen = set(state.get("seen_target_ids", []))
        seen.update(target.node_id for target in result.targets)

        return {
            "status": "targets_ready",
            "targets": list(result.targets),
            "next_targets": [],
            "seen_target_ids": sorted(seen),
            "exploration_reason": result.reason,
            "error": None,
        }

    @staticmethod
    def _after_explore(
        state: DeepSearchState,
    ) -> str:
        if state.get("status") == "targets_ready" and state.get("targets"):
            return "retrieve"

        return "finalize"

    # ------------------------------------------------------------------
    # Stage 3: retrieve code through the existing search adapter
    # ------------------------------------------------------------------

    def _retrieve(
        self,
        state: DeepSearchState,
    ) -> dict[str, Any]:
        query = (
            state.get("retrieval_query")
            or state.get("query")
            or ""
        )

        result = self.retriever.retrieve(
            query=query,
            targets=state.get("targets", []),
            state=state,
        )

        status = result.get("status", "UNAVAILABLE")

        if status != "SUCCESS":
            return {
                "retrieval_status": status,
                "status": (
                    "unavailable"
                    if status == "UNAVAILABLE"
                    else "incomplete"
                ),
                "missing_targets": result.get("missing_targets", []),
                "error": result.get(
                    "reason",
                    "Targeted retrieval did not return usable code.",
                ),
            }

        # Preserve evidence from earlier rounds and deduplicate by path,
        # content and start line.
        all_chunks = list(state.get("retrieved_chunks", []))
        seen = {
            (
                chunk.get("path"),
                chunk.get("content"),
                chunk.get("line_start"),
            )
            for chunk in all_chunks
            if isinstance(chunk, Mapping)
        }

        for chunk in result.get("retrieved_chunks", []):
            signature = (
                chunk.get("path"),
                chunk.get("content"),
                chunk.get("line_start"),
            )

            if signature not in seen:
                all_chunks.append(chunk)
                seen.add(signature)

        return {
            "status": "retrieval_ready",
            "retrieval_status": status,
            "retrieved_chunks": all_chunks,
            "missing_targets": result.get("missing_targets", []),
            "error": None,
        }

    @staticmethod
    def _after_retrieval(
        state: DeepSearchState,
    ) -> str:
        if (
            state.get("status") == "retrieval_ready"
            and state.get("retrieved_chunks")
        ):
            return "assess"

        return "finalize"

    # ------------------------------------------------------------------
    # Stage 4: assess evidence and request a bounded follow-up if needed
    # ------------------------------------------------------------------

    def _assess(
        self,
        state: DeepSearchState,
    ) -> dict[str, Any]:
        dependency_graph = state.get("dependency_graph")

        assessment_state = {
            "query": state.get("query", ""),
            "intent": state.get("intent", "FIX_BUG"),
            "targets": state.get("targets", []),
            "retrieved_chunks": state.get("retrieved_chunks", []),
            "dependency_graph": dependency_graph,
            "unresolved_references": state.get(
                "unresolved_references", []
            ),
            "rounds": state.get("rounds", 0),
            "max_rounds": state.get("max_rounds", self.max_rounds),
        }

        result = self.assessor.assess(assessment_state)
        assessment_status = result.get("status", "unavailable")

        if assessment_status == "running":
            follow_up_targets = result.get("follow_up_targets", [])
            follow_up_query = result.get("follow_up_query")

            if not follow_up_targets:
                return {
                    "status": "incomplete",
                    "assessment": result,
                    "assessment_status": "incomplete",
                    "error": (
                        "The assessor requested further investigation but "
                        "provided no verified targets."
                    ),
                }

            return {
                "status": "follow_up_requested",
                "assessment": result,
                "assessment_status": assessment_status,
                "next_targets": follow_up_targets,
                "retrieval_query": (
                    follow_up_query
                    if isinstance(follow_up_query, str)
                    and follow_up_query.strip()
                    else state.get("query", "")
                ),
                "rounds": state.get("rounds", 0) + 1,
                "error": None,
            }

        if assessment_status == "complete":
            return {
                "status": "assessment_complete",
                "assessment": result,
                "assessment_status": "complete",
                "diagnosis": result.get("diagnosis"),
                "confidence": result.get("confidence", 0.0),
                "evidence": result.get("evidence", []),
                "error": None,
            }

        # Both incomplete and unavailable are terminal; neither means success.
        terminal_status = (
            "unavailable"
            if assessment_status == "unavailable"
            else "incomplete"
        )

        return {
            "status": terminal_status,
            "assessment": result,
            "assessment_status": assessment_status,
            "error": result.get(
                "reason",
                "The diagnosis could not be established.",
            ),
        }

    @staticmethod
    def _after_assessment(
        state: DeepSearchState,
    ) -> str:
        if state.get("status") == "follow_up_requested":
            rounds = state.get("rounds", 0)
            max_rounds = state.get("max_rounds", DEFAULT_MAX_ROUNDS)

            if rounds < max_rounds:
                return "explore"

        return "finalize"

    # ------------------------------------------------------------------
    # Stage 5: consistent terminal result
    # ------------------------------------------------------------------

    def _finalize(
        self,
        state: DeepSearchState,
    ) -> dict[str, Any]:
        assessment = state.get("assessment", {})
        if not isinstance(assessment, Mapping):
            assessment = {}

        status = state.get("status", "incomplete")

        if status == "assessment_complete":
            final_status = "complete"
        elif status == "unavailable":
            final_status = "unavailable"
        else:
            final_status = "incomplete"

        result = {
            "status": final_status,
            "intent": "FIX_BUG",
            "repo_name": state.get("repo_name"),
            "diagnosis": (
                assessment.get("diagnosis")
                if final_status == "complete"
                else None
            ),
            "confidence": (
                assessment.get("confidence", 0.0)
                if final_status == "complete"
                else 0.0
            ),
            "evidence": assessment.get("evidence", []),
            "retrieved_chunks": state.get("retrieved_chunks", []),
            "searched_targets": [
                target.path
                if hasattr(target, "path")
                else str(target)
                for target in state.get("targets", [])
            ],
            "missing_targets": state.get("missing_targets", []),
            "rounds": state.get("rounds", 0),
            "reason": (
                assessment.get("reason")
                or state.get("error")
                or state.get("exploration_reason")
                or "Deep Search finished without a verified diagnosis."
            ),
            "graph_metadata": state.get("graph_metadata", {}),
        }

        return {
            "final_result": result,
            "status": final_status,
        }

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _collection_from_selection(selection: Any) -> Optional[str]:
        if isinstance(selection, str) and selection.strip():
            return selection.strip()

        if isinstance(selection, Mapping):
            for key in (
                "collection_name",
                "resolved_collection",
                "selected_collection",
            ):
                value = selection.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        if selection is not None:
            for key in (
                "collection_name",
                "resolved_collection",
                "selected_collection",
            ):
                value = getattr(selection, key, None)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        return None

    @staticmethod
    def _terminal_result(
        *,
        status: str,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "status": status,
            "intent": "FIX_BUG",
            "diagnosis": None,
            "confidence": 0.0,
            "evidence": [],
            "retrieved_chunks": [],
            "searched_targets": [],
            "missing_targets": [],
            "rounds": 0,
            "reason": reason,
        }


class DeepSearchStage:
    """
    Adapter for RepoLens's stage-based search pipeline.

    Do not place this stage after CodeRetrievalStage. Integrate it at the
    pre-retrieval decision point so Deep Search does not depend on initial
    semantic retrieval results.

    The integration layer must set context.deep_search_requested based on
    decide_deep_search() and make the repository's resolved collection
    available before invoking this stage.
    """

    def __init__(
        self,
        *,
        workflow: Optional[DeepSearchWorkflow] = None,
        **workflow_dependencies: Any,
    ) -> None:
        self.workflow = workflow or DeepSearchWorkflow(
            **workflow_dependencies
        )

    def execute(self, context: Any) -> Any:
        intent = self._context_value(
            context,
            "intent",
            "classified_intent",
            "request_intent",
        )

        requested = self._context_value(
            context,
            "deep_search_requested",
        )

        # Normal FIX_BUG requests and every other intent continue through
        # the existing search flow.
        if str(intent or "").strip().upper() != "FIX_BUG":
            return context

        if requested is not True:
            return context

        state = {
            "query": self._context_value(context, "query") or "",
            "intent": "FIX_BUG",
            "deep_search_requested": True,
            "repo_name": self._context_value(
                context,
                "repo_name",
                "repository_name",
            ),
            "collection_name": self._context_value(
                context,
                "collection_name",
                "resolved_collection",
                "selected_collection",
            ),
            "collection_selection": self._context_value(
                context,
                "collection_selection",
            ),
            "source_type": self._context_value(context, "source_type"),
            "source_location": self._context_value(
                context,
                "source_location",
            ),
        }

        result = self.workflow.run(state)

        self._set_context_value(
            context,
            "deep_search_result",
            result,
        )

        # Deep Search produces its own terminal diagnosis/evidence result.
        # Downstream ordinary analysis stages should not overwrite it.
        self._set_context_value(context, "early_exit", True)

        return context

    @staticmethod
    def _context_value(context: Any, *names: str) -> Any:
        for name in names:
            if isinstance(context, Mapping):
                value = context.get(name)
            else:
                value = getattr(context, name, None)

            if value is not None:
                return value

        return None

    @staticmethod
    def _set_context_value(
        context: Any,
        name: str,
        value: Any,
    ) -> None:
        try:
            setattr(context, name, value)
        except (AttributeError, TypeError, ValueError):
            # Some context objects constrain fields. Do not silently mutate
            # an unrelated field or report successful integration.
            raise RuntimeError(
                f"SearchContext does not permit setting {name!r}. "
                "Add the field to its existing definition before integration."
            )
