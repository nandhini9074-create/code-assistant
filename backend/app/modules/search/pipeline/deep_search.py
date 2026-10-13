
"""
app/modules/search/pipeline/deep_search.py

Bounded Deep Search workflow for FIX_BUG requests.

Deep Search is optional and runs only when explicitly selected.
It acquires a read-only source snapshot, builds and explores the
dependency graph, retrieves targeted code through the existing search
adapter, assesses evidence, and returns a bounded terminal result.

This module never writes repository files, creates a Qdrant client,
uses ZIP-based repository identification, or changes normal search flow.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Mapping
from typing import Any, Callable, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from app.modules.search.pipeline.dependency_graph import (
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
from app.modules.search.pipeline.deep_search_source_provider import (
    DeepSearchSourceError,
    provide_source_files,
)

logger = logging.getLogger(__name__)

MAX_INVESTIGATION_ROUNDS = 3
MAX_GRAPH_DEPTH = 3
MAX_TARGETS = 12

STATUS_RUNNING = "running"
STATUS_COMPLETE = "complete"
STATUS_INCOMPLETE = "incomplete"
STATUS_UNAVAILABLE = "unavailable"

INTENT_FIX_BUG = "FIX_BUG"

# The workflow provider is synchronous. The stage provider can be async.
SourceProvider = Callable[[Mapping[str, Any]], Mapping[str, str]]
AsyncSourceProvider = Callable[
    [Mapping[str, Any]],
    Awaitable[Mapping[str, str]],
]


class DeepSearchState(TypedDict, total=False):
    """State shared between LangGraph nodes."""

    query: str
    intent: str
    deep_search_requested: bool

    repo_name: Optional[str]
    collection_name: Optional[str]
    resolved_collection: Optional[str]
    selected_collection: Optional[str]
    qdrant_collection: Optional[str]
    collection_selection: Any

    source_type: Optional[str]
    source_location: Optional[str]
    source_files: Mapping[str, str]

    status: str
    error: Optional[str]
    diagnostic_code: Optional[str]

    dependency_graph: Any
    graph_metadata: dict[str, Any]
    unresolved_references: list[Any]

    targets: list[Any]
    next_targets: list[Any]
    seen_target_ids: list[str]

    retrieved_chunks: list[Any]
    missing_targets: list[Any]
    retrieval_status: Optional[str]
    retrieval_query: Optional[str]

    rounds: int
    max_rounds: int
    max_graph_depth: int
    max_targets: int

    assessment: dict[str, Any]
    assessment_status: Optional[str]

    diagnosis: Optional[str]
    confidence: Optional[float]
    evidence: list[Any]
    reason: Optional[str]

    final_result: dict[str, Any]


def _safe_count(value: Any) -> int:
    """Return a collection size without allowing diagnostic code to fail."""
    try:
        return len(value)
    except (TypeError, AttributeError):
        return 0


def _safe_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _normalize_intent(value: Any) -> str:
    """Normalize string and Enum intent values to their canonical name."""
    if value is None:
        return ""

    value = getattr(value, "value", value)
    normalized = str(value).strip().upper()

    # Handle Enum-like string representations such as Intent.FIX_BUG.
    if "." in normalized:
        normalized = normalized.rsplit(".", 1)[-1]

    return normalized


def _target_id(target: Any) -> str:
    for key in ("target_id", "id", "path", "file_path", "name"):
        if isinstance(target, Mapping):
            value = target.get(key)
        else:
            value = getattr(target, key, None)

        if value is not None:
            return str(value)

    return str(target)


def _target_list(value: Any) -> list[Any]:
    if value is None:
        return []

    if isinstance(value, (list, tuple)):
        return list(value)

    for key in ("targets", "items", "results"):
        candidate = (
            value.get(key)
            if isinstance(value, Mapping)
            else getattr(value, key, None)
        )
        if isinstance(candidate, (list, tuple)):
            return list(candidate)

    return []


def _unique_targets(targets: list[Any]) -> list[Any]:
    """Deduplicate targets without requiring hashable target objects."""
    result: list[Any] = []
    seen: set[str] = set()

    for target in targets:
        identifier = _target_id(target)
        if identifier not in seen:
            seen.add(identifier)
            result.append(target)

    return result


class DeepSearchWorkflow:
    """Orchestrate a bounded dependency-graph investigation."""

    def __init__(
        self,
        source_provider: Optional[SourceProvider] = None,
        search_adapter: Any = None,
        assessment_adapter: Any = None,
        explorer: Optional[DeepSearchExplorer] = None,
        retriever: Optional[DeepSearchRetriever] = None,
        assessor: Optional[DeepSearchAssessor] = None,
        max_rounds: int = MAX_INVESTIGATION_ROUNDS,
        max_graph_depth: int = MAX_GRAPH_DEPTH,
        max_targets: int = MAX_TARGETS,
    ) -> None:
        self.source_provider = source_provider

        self.max_rounds = max(
            1, min(int(max_rounds), MAX_INVESTIGATION_ROUNDS)
        )
        self.max_graph_depth = max(
            1, min(int(max_graph_depth), MAX_GRAPH_DEPTH)
        )
        self.max_targets = max(
            1, min(int(max_targets), MAX_TARGETS)
        )

        self.explorer = explorer or DeepSearchExplorer()
        self.retriever = retriever or DeepSearchRetriever(
            search_adapter=search_adapter
        )
        self.assessor = assessor or DeepSearchAssessor(
            assessment_adapter=assessment_adapter
        )

        self.app = self._build_graph()

        logger.info(
            "deep_search_workflow_initialized",
            extra={
                "source_provider_configured": (
                    self.source_provider is not None
                ),
                "search_adapter_configured": search_adapter is not None,
                "assessment_adapter_configured": (
                    assessment_adapter is not None
                ),
                "max_rounds": self.max_rounds,
                "max_graph_depth": self.max_graph_depth,
                "max_targets": self.max_targets,
            },
        )

    @staticmethod
    def _resolve_collection(
        state: Mapping[str, Any],
    ) -> Optional[str]:
        """Resolve only the collection already selected by the application."""
        for key in (
            "collection_name",
            "resolved_collection",
            "selected_collection",
            "qdrant_collection",
        ):
            value = state.get(key)
            if value:
                return str(value).strip()

        selection = state.get("collection_selection")

        for key in (
            "collection_name",
            "resolved_collection",
            "selected_collection",
            "collection",
        ):
            value = (
                selection.get(key)
                if isinstance(selection, Mapping)
                else getattr(selection, key, None)
                if selection is not None
                else None
            )
            if value:
                return str(value).strip()

        return None

    def _build_graph(self):
        graph = StateGraph(DeepSearchState)

        graph.add_node("validate", self._validate_input)
        graph.add_node(
            "build_dependency_graph",
            self._build_dependency_graph,
        )
        graph.add_node("explore", self._explore)
        graph.add_node("retrieve", self._retrieve)
        graph.add_node("assess", self._assess)
        graph.add_node("finalize", self._finalize)

        graph.add_edge(START, "validate")

        graph.add_conditional_edges(
            "validate",
            self._route_after_validation,
            {
                "build_dependency_graph": "build_dependency_graph",
                "finalize": "finalize",
            },
        )

        graph.add_conditional_edges(
            "build_dependency_graph",
            self._route_after_graph_build,
            {
                "explore": "explore",
                "finalize": "finalize",
            },
        )

        graph.add_conditional_edges(
            "explore",
            self._route_after_exploration,
            {
                "retrieve": "retrieve",
                "finalize": "finalize",
            },
        )

        graph.add_conditional_edges(
            "retrieve",
            self._route_after_retrieval,
            {
                "assess": "assess",
                "finalize": "finalize",
            },
        )

        graph.add_conditional_edges(
            "assess",
            self._route_after_assessment,
            {
                "explore": "explore",
                "finalize": "finalize",
            },
        )

        graph.add_edge("finalize", END)
        return graph.compile()

    @staticmethod
    def _route_after_validation(state: DeepSearchState) -> str:
        return (
            "build_dependency_graph"
            if state.get("status") == STATUS_RUNNING
            else "finalize"
        )

    @staticmethod
    def _route_after_graph_build(state: DeepSearchState) -> str:
        return (
            "explore"
            if state.get("status") == STATUS_RUNNING
            else "finalize"
        )

    @staticmethod
    def _route_after_exploration(state: DeepSearchState) -> str:
        return (
            "retrieve"
            if state.get("status") == STATUS_RUNNING
            and state.get("targets")
            else "finalize"
        )

    @staticmethod
    def _route_after_retrieval(state: DeepSearchState) -> str:
        return (
            "assess"
            if state.get("status") == STATUS_RUNNING
            and state.get("retrieved_chunks")
            else "finalize"
        )

    @staticmethod
    def _route_after_assessment(state: DeepSearchState) -> str:
        return (
            "explore"
            if state.get("status") == STATUS_RUNNING
            and state.get("next_targets")
            and state.get("rounds", 0) < state.get("max_rounds", 1)
            else "finalize"
        )

    @staticmethod
    def _input_error(
        state: Mapping[str, Any],
    ) -> Optional[str]:
        """Validate inputs consistently before graph construction."""
        if not _safe_text(state.get("query")):
            return "Deep Search requires a non-empty query."

        intent = _normalize_intent(state.get("intent"))
        if intent != INTENT_FIX_BUG:
            return (
                "Deep Search is only supported for FIX_BUG requests. "
                f"Received intent: {intent or 'missing'}."
            )

        if state.get("deep_search_requested") is not True:
            return "Deep Search was not selected for this request."

        if not _safe_text(state.get("repo_name")):
            return "Deep Search requires a resolved repository name."

        if not DeepSearchWorkflow._resolve_collection(state):
            return "Deep Search requires a resolved search collection."

        return None

    def run(self, initial_state: Mapping[str, Any]) -> dict[str, Any]:
        """Run the graph synchronously and return a terminal result."""
        state: DeepSearchState = dict(initial_state)
        state["intent"] = _normalize_intent(state.get("intent"))

        state.setdefault("rounds", 0)
        state.setdefault("max_rounds", self.max_rounds)
        state.setdefault("max_graph_depth", self.max_graph_depth)
        state.setdefault("max_targets", self.max_targets)
        state.setdefault("targets", [])
        state.setdefault("next_targets", [])
        state.setdefault("seen_target_ids", [])
        state.setdefault("retrieved_chunks", [])
        state.setdefault("missing_targets", [])
        state.setdefault("evidence", [])
        state.setdefault("unresolved_references", [])
        state.setdefault("graph_metadata", {})
        state.setdefault("assessment", {})
        state.setdefault("status", STATUS_RUNNING)

        try:
            state["max_rounds"] = max(
                1, min(int(state["max_rounds"]), self.max_rounds)
            )
            state["max_graph_depth"] = max(
                1,
                min(
                    int(state["max_graph_depth"]),
                    self.max_graph_depth,
                ),
            )
            state["max_targets"] = max(
                1, min(int(state["max_targets"]), self.max_targets)
            )
        except (TypeError, ValueError):
            state["status"] = STATUS_UNAVAILABLE
            state["reason"] = "Deep Search limits are invalid."
            state["diagnostic_code"] = "DEEP_SEARCH_LIMITS_INVALID"
            return self._terminal_result(state)

        validation_error = self._input_error(state)

        logger.info(
            "deep_search_input_validation",
            extra={
                "intent": state.get("intent"),
                "deep_search_requested": state.get(
                    "deep_search_requested"
                ),
                "validation_error": validation_error,
                "repo_name_present": bool(state.get("repo_name")),
                "collection_name": self._resolve_collection(state),
                "source_files_provided": isinstance(
                    state.get("source_files"), Mapping
                ),
                "source_provider_configured": (
                    self.source_provider is not None
                ),
            },
        )

        logger.info(
            "deep_search_workflow_started",
            extra={
                "repo_name": state.get("repo_name"),
                "collection_name": self._resolve_collection(state),
                "intent": state.get("intent"),
                "source_files_provided": isinstance(
                    state.get("source_files"), Mapping
                ),
                "max_rounds": state["max_rounds"],
                "max_graph_depth": state["max_graph_depth"],
                "max_targets": state["max_targets"],
            },
        )

        if validation_error:
            state["status"] = STATUS_UNAVAILABLE
            state["reason"] = validation_error
            state["diagnostic_code"] = "DEEP_SEARCH_INPUT_INVALID"

            logger.error(
                "deep_search_input_rejected",
                extra={
                    "diagnostic_code": state["diagnostic_code"],
                    "reason": validation_error,
                    "intent": state.get("intent"),
                    "repo_name": state.get("repo_name"),
                    "collection_name": self._resolve_collection(state),
                },
            )
            return self._terminal_result(state)

        try:
            completed = self.app.invoke(state)

            if not isinstance(completed, Mapping):
                raise TypeError(
                    "LangGraph returned a non-mapping state."
                )

            final_result = completed.get("final_result")

            if isinstance(final_result, Mapping):
                return dict(final_result)

            logger.error(
                "deep_search_final_result_missing",
                extra={
                    "status": completed.get("status"),
                    "reason": completed.get("reason"),
                    "diagnostic_code": (
                        "DEEP_SEARCH_FINAL_RESULT_MISSING"
                    ),
                },
            )

            failed_state = dict(completed)
            failed_state["status"] = STATUS_UNAVAILABLE
            failed_state["reason"] = (
                "Deep Search finished without producing a final result."
            )
            failed_state["diagnostic_code"] = (
                "DEEP_SEARCH_FINAL_RESULT_MISSING"
            )
            return self._terminal_result(failed_state)

        except Exception:
            logger.exception(
                "deep_search_workflow_failed",
                extra={
                    "repo_name": state.get("repo_name"),
                    "collection_name": self._resolve_collection(state),
                    "rounds": state.get("rounds", 0),
                },
            )

            state["status"] = STATUS_UNAVAILABLE
            state["reason"] = (
                "Deep Search workflow execution failed. "
                "Inspect the server traceback using the request ID."
            )
            state["diagnostic_code"] = "DEEP_SEARCH_WORKFLOW_EXCEPTION"
            return self._terminal_result(state)

    def _validate_input(
        self,
        state: DeepSearchState,
    ) -> dict[str, Any]:
        reason = self._input_error(state)

        if reason:
            logger.error(f"[DeepSearch] Input validation failed: {reason}")
            logger.error(
                "deep_search_validation_failed",
                extra={
                    "diagnostic_code": "DEEP_SEARCH_INPUT_INVALID",
                    "reason": reason,
                    "intent": _normalize_intent(state.get("intent")),
                },
            )
            return {
                "status": STATUS_UNAVAILABLE,
                "reason": reason,
                "diagnostic_code": "DEEP_SEARCH_INPUT_INVALID",
            }

        return {"status": STATUS_RUNNING}

    def _build_dependency_graph(
        self,
        state: DeepSearchState,
    ) -> dict[str, Any]:
        """Build the graph from the source snapshot supplied by the stage."""
        logger.info(
            "deep_search_graph_build_started",
            extra={
                "repo_name": state.get("repo_name"),
                "collection_name": self._resolve_collection(state),
                "source_files_provided": isinstance(
                    state.get("source_files"), Mapping
                ),
            },
        )

        source_files = state.get("source_files")

        # This workflow is synchronous. Asynchronous source acquisition
        # belongs in DeepSearchStage.execute(), before app.invoke().
        if source_files is None and self.source_provider is not None:
            try:
                source_files = self.source_provider(dict(state))

                if inspect.isawaitable(source_files):
                    close = getattr(source_files, "close", None)
                    if callable(close):
                        close()
                    raise TypeError(
                        "DeepSearchWorkflow requires a synchronous "
                        "source_provider. Await async providers in "
                        "DeepSearchStage.execute()."
                    )
            except Exception:
                logger.exception("deep_search_source_acquisition_failed")
                return {
                    "status": STATUS_UNAVAILABLE,
                    "reason": "Source acquisition failed.",
                    "diagnostic_code": (
                        "DEEP_SEARCH_SOURCE_ACQUISITION_FAILED"
                    ),
                }

        if source_files is None:
            logger.error(
                f"[DeepSearch] No source files available for repository '{state.get('repo_name')}'. Cannot build dependency graph."
            )
            logger.error(
                "deep_search_source_provider_missing",
                extra={
                    "diagnostic_code": (
                        "DEEP_SEARCH_SOURCE_PROVIDER_MISSING"
                    ),
                    "repo_name": state.get("repo_name"),
                    "collection_name": self._resolve_collection(state),
                },
            )
            return {
                "status": STATUS_UNAVAILABLE,
                "reason": (
                    "No source files were supplied and no source "
                    "provider is configured for Deep Search."
                ),
                "diagnostic_code": "DEEP_SEARCH_SOURCE_PROVIDER_MISSING",
            }

        if not isinstance(source_files, Mapping) or not source_files:
            logger.error(
                f"[DeepSearch] Source files empty for repository '{state.get('repo_name')}'. Cannot build dependency graph."
            )
            return {
                "status": STATUS_UNAVAILABLE,
                "reason": (
                    "Source acquisition returned no usable source files."
                ),
                "diagnostic_code": "DEEP_SEARCH_SOURCE_FILES_EMPTY",
            }

        validated_files: dict[str, str] = {}

        for path, source in source_files.items():
            if not isinstance(path, str) or not path.strip():
                return {
                    "status": STATUS_UNAVAILABLE,
                    "reason": (
                        "Source snapshot contains an invalid file path."
                    ),
                    "diagnostic_code": "DEEP_SEARCH_SOURCE_PATH_INVALID",
                }

            normalized_path = path.strip().replace("\\", "/")
            parts = normalized_path.split("/")

            if (
                normalized_path.startswith("/")
                or (
                    len(normalized_path) > 1
                    and normalized_path[1] == ":"
                )
                or any(part == ".." for part in parts)
                or any(part in ("", ".") for part in parts)
            ):
                return {
                    "status": STATUS_UNAVAILABLE,
                    "reason": (
                        "Source snapshot contains an unsafe file path."
                    ),
                    "diagnostic_code": "DEEP_SEARCH_SOURCE_PATH_UNSAFE",
                }

            if not isinstance(source, str):
                logger.error(f"[DeepSearch] Source snapshot contains non-text file content for '{normalized_path}'.")
                return {
                    "status": STATUS_UNAVAILABLE,
                    "reason": (
                        "Source snapshot contains non-text file content."
                    ),
                    "diagnostic_code": (
                        "DEEP_SEARCH_SOURCE_CONTENT_INVALID"
                    ),
                }

            validated_files[normalized_path] = source

        try:
            graph = build_dependency_graph(validated_files)
        except Exception as exc:
            logger.error(
                f"[DeepSearch] Dependency graph construction failed for repo '{state.get('repo_name')}': {exc}",
                exc_info=True,
            )
            return {
                "status": STATUS_UNAVAILABLE,
                "reason": "Dependency graph construction failed.",
                "diagnostic_code": "DEEP_SEARCH_GRAPH_BUILD_FAILED",
            }

        nodes = getattr(graph, "nodes", [])
        edges = getattr(graph, "edges", [])
        unresolved = getattr(
            graph,
            "unresolved_references",
            getattr(graph, "unresolved", []),
        )
        metadata = getattr(graph, "metadata", {})

        if not isinstance(metadata, Mapping):
            metadata = {}

        graph_metadata = dict(metadata)
        graph_metadata.update(
            {
                "node_count": _safe_count(nodes),
                "edge_count": _safe_count(edges),
                "source_file_count": len(validated_files),
            }
        )

        logger.info(
            "deep_search_graph_build_completed",
            extra={
                "node_count": _safe_count(nodes),
                "edge_count": _safe_count(edges),
                "source_file_count": len(validated_files),
                "unresolved_reference_count": _safe_count(unresolved),
                "max_graph_depth": state["max_graph_depth"],
            },
        )

        if _safe_count(nodes) == 0:
            logger.warning(
                f"[DeepSearch] Dependency graph contains 0 nodes for repo '{state.get('repo_name')}'. Source files count: {len(validated_files)}."
            )
            return {
                "status": STATUS_INCOMPLETE,
                "reason": (
                    "The source snapshot was acquired, but the "
                    "dependency graph contains no nodes."
                ),
                "diagnostic_code": "DEEP_SEARCH_GRAPH_EMPTY",
                "graph_metadata": graph_metadata,
                "unresolved_references": list(unresolved or []),
            }

        return {
            "status": STATUS_RUNNING,
            "dependency_graph": graph,
            "graph_metadata": graph_metadata,
            "unresolved_references": list(unresolved or []),
        }

    def _explore(
        self,
        state: DeepSearchState,
    ) -> dict[str, Any]:
        """Explore graph targets within the configured bounds."""
        graph = state.get("dependency_graph")

        if graph is None:
            return {
                "status": STATUS_UNAVAILABLE,
                "reason": "Dependency graph is unavailable.",
                "diagnostic_code": "DEEP_SEARCH_GRAPH_MISSING",
            }

        try:
            explore_method = self.explorer.explore
            parameters = inspect.signature(explore_method).parameters

            kwargs: dict[str, Any] = {
                "query": state["query"],
                "graph": graph,
                "initial_targets": state.get("next_targets") or None,
                "previous_targets": state.get("seen_target_ids", []),
            }

            if "max_graph_depth" in parameters:
                kwargs["max_graph_depth"] = state["max_graph_depth"]
            elif "max_depth" in parameters:
                kwargs["max_depth"] = state["max_graph_depth"]

            result = explore_method(**kwargs)

        except Exception as exc:
            logger.error(f"[DeepSearch] Graph exploration failed: {exc}", exc_info=True)
            return {
                "status": STATUS_UNAVAILABLE,
                "reason": "Dependency graph exploration failed.",
                "diagnostic_code": "DEEP_SEARCH_EXPLORATION_FAILED",
            }

        targets = _unique_targets(_target_list(result))
        targets = targets[: state["max_targets"]]

        reason = (
            result.get("reason")
            if isinstance(result, Mapping)
            else getattr(result, "reason", None)
        )

        if not targets:
            logger.warning(
                f"[DeepSearch] Exploration found 0 targets in round {state.get('rounds', 0)}: {reason or 'no matching targets'}."
            )
            return {
                "status": STATUS_INCOMPLETE,
                "targets": [],
                "next_targets": [],
                "reason": reason
                or "No relevant graph targets were identified.",
                "diagnostic_code": "DEEP_SEARCH_NO_TARGETS",
            }

        seen = list(state.get("seen_target_ids", []))
        seen_set = set(seen)

        for target in targets:
            identifier = _target_id(target)
            if identifier not in seen_set:
                seen.append(identifier)
                seen_set.add(identifier)

        logger.info(
            "deep_search_exploration_completed",
            extra={
                "round": state.get("rounds", 0),
                "target_count": len(targets),
                "seen_target_count": len(seen),
                "max_graph_depth": state["max_graph_depth"],
            },
        )

        return {
            "status": STATUS_RUNNING,
            "targets": targets,
            "next_targets": [],
            "seen_target_ids": seen,
        }

    def _retrieve(
        self,
        state: DeepSearchState,
    ) -> dict[str, Any]:
        """Retrieve graph-selected targets through the existing adapter."""
        targets = state.get("targets", [])

        if not targets:
            return {
                "status": STATUS_INCOMPLETE,
                "retrieval_status": "NO_TARGETS",
                "reason": "No graph targets were available for retrieval.",
                "diagnostic_code": "DEEP_SEARCH_RETRIEVAL_NO_TARGETS",
            }

        try:
            result = self.retriever.retrieve(
                query=state.get("retrieval_query") or state["query"],
                targets=targets,
                state=state,
            )
        except Exception as exc:
            logger.error(
                f"[DeepSearch] Targeted code retrieval failed in round {state.get('rounds', 0)}: {exc}",
                exc_info=True,
            )
            return {
                "status": STATUS_UNAVAILABLE,
                "retrieval_status": "ERROR",
                "reason": "Targeted code retrieval failed.",
                "diagnostic_code": "DEEP_SEARCH_RETRIEVAL_FAILED",
            }

        if not isinstance(result, Mapping):
            logger.error("[DeepSearch] Targeted retrieval returned an invalid non-mapping result.")
            return {
                "status": STATUS_UNAVAILABLE,
                "retrieval_status": "INVALID_RESULT",
                "reason": (
                    "The retrieval adapter returned an invalid result."
                ),
                "diagnostic_code": (
                    "DEEP_SEARCH_RETRIEVAL_RESULT_INVALID"
                ),
            }

        retrieval_status = result.get("status")
        chunks = result.get("retrieved_chunks", [])
        missing = result.get("missing_targets", [])

        if not isinstance(chunks, list):
            chunks = []
        if not isinstance(missing, list):
            missing = []

        if retrieval_status != "SUCCESS":
            logger.warning(
                f"[DeepSearch] Targeted retrieval incomplete (status='{retrieval_status}', "
                f"chunks={len(chunks)}, missing={len(missing)} targets)."
            )
            return {
                "status": STATUS_INCOMPLETE,
                "retrieval_status": retrieval_status,
                "retrieved_chunks": chunks,
                "missing_targets": missing,
                "reason": (
                    "Targeted retrieval did not report success; "
                    "the evidence cannot be treated as complete."
                ),
                "diagnostic_code": (
                    "DEEP_SEARCH_RETRIEVAL_INCOMPLETE"
                ),
            }

        if not chunks:
            logger.warning(f"[DeepSearch] Targeted retrieval returned 0 chunks for targets: {targets}.")
            return {
                "status": STATUS_INCOMPLETE,
                "retrieval_status": retrieval_status,
                "retrieved_chunks": [],
                "missing_targets": missing,
                "reason": "Targeted retrieval returned no code chunks.",
                "diagnostic_code": "DEEP_SEARCH_RETRIEVAL_EMPTY",
            }

        merged: list[Any] = []
        keys: set[tuple[str, str, str]] = set()

        for chunk in list(state.get("retrieved_chunks", [])) + chunks:
            if isinstance(chunk, Mapping):
                path = str(
                    chunk.get("path")
                    or chunk.get("file_path")
                    or chunk.get("source")
                    or ""
                )
                content = str(
                    chunk.get("content")
                    or chunk.get("code")
                    or chunk.get("text")
                    or ""
                )
                line = str(
                    chunk.get("line_start")
                    or chunk.get("start_line")
                    or ""
                )
            else:
                path = str(
                    getattr(chunk, "path", "")
                    or getattr(chunk, "file_path", "")
                )
                content = str(
                    getattr(
                        chunk,
                        "content",
                        getattr(chunk, "code", ""),
                    )
                )
                line = str(
                    getattr(
                        chunk,
                        "line_start",
                        getattr(chunk, "start_line", ""),
                    )
                )

            key = (path, content, line)
            if key not in keys:
                keys.add(key)
                merged.append(chunk)

        logger.info(
            "deep_search_retrieval_completed",
            extra={
                "round": state.get("rounds", 0),
                "target_count": len(targets),
                "retrieved_chunk_count": len(merged),
                "missing_target_count": len(missing),
                "retrieval_status": retrieval_status,
            },
        )

        return {
            "status": STATUS_RUNNING,
            "retrieval_status": retrieval_status,
            "retrieved_chunks": merged,
            "missing_targets": missing,
            "retrieval_query": result.get("retrieval_query"),
        }

    def _assess(
        self,
        state: DeepSearchState,
    ) -> dict[str, Any]:
        """Assess retrieved evidence and schedule bounded follow-up work."""
        round_number = int(state.get("rounds", 0)) + 1
        max_rounds = int(state.get("max_rounds", self.max_rounds))

        try:
            result = self.assessor.assess(
                query=state["query"],
                intent=_normalize_intent(
                    state.get("intent", INTENT_FIX_BUG)
                ),
                targets=state.get("targets", []),
                retrieved_chunks=state.get("retrieved_chunks", []),
                dependency_graph=state.get("dependency_graph"),
                unresolved_references=state.get(
                    "unresolved_references", []
                ),
                rounds=round_number,
                max_rounds=max_rounds,
            )
        except Exception as exc:
            logger.error(
                f"[DeepSearch] Evidence assessment failed in round {round_number}: {exc}",
                exc_info=True,
            )
            return {
                "status": STATUS_UNAVAILABLE,
                "rounds": round_number,
                "assessment_status": "ERROR",
                "reason": "Evidence assessment failed.",
                "diagnostic_code": "DEEP_SEARCH_ASSESSMENT_FAILED",
            }

        if not isinstance(result, Mapping):
            logger.error(f"[DeepSearch] Assessment adapter returned an invalid non-mapping result in round {round_number}.")
            return {
                "status": STATUS_UNAVAILABLE,
                "rounds": round_number,
                "assessment_status": "INVALID_RESULT",
                "reason": "The assessor returned an invalid result.",
                "diagnostic_code": (
                    "DEEP_SEARCH_ASSESSMENT_RESULT_INVALID"
                ),
            }

        assessment = dict(result)
        assessment_status = assessment.get("status")
        diagnosis = assessment.get("diagnosis")
        evidence = assessment.get("evidence", [])

        if not isinstance(evidence, list):
            evidence = []

        if assessment_status == STATUS_RUNNING:
            if round_number >= max_rounds:
                logger.warning(
                    f"[DeepSearch] Round limit reached ({round_number}/{max_rounds}) without conclusive evidence."
                )
                return {
                    "status": STATUS_INCOMPLETE,
                    "rounds": round_number,
                    "assessment": assessment,
                    "assessment_status": "round_limit_reached",
                    "reason": (
                        "The investigation reached its configured round "
                        "limit before evidence was sufficient."
                    ),
                    "diagnostic_code": (
                        "DEEP_SEARCH_ROUND_LIMIT_REACHED"
                    ),
                }

            follow_up = _unique_targets(
                _target_list(
                    assessment.get("follow_up_targets")
                    or assessment.get("next_targets")
                )
            )[: state["max_targets"]]

            if not follow_up:
                return {
                    "status": STATUS_INCOMPLETE,
                    "rounds": round_number,
                    "assessment": assessment,
                    "assessment_status": "follow_up_targets_missing",
                    "reason": (
                        "Assessment requested further investigation but "
                        "provided no follow-up targets."
                    ),
                    "diagnostic_code": (
                        "DEEP_SEARCH_FOLLOW_UP_TARGETS_MISSING"
                    ),
                }

            seen = set(state.get("seen_target_ids", []))
            new_targets = [
                target
                for target in follow_up
                if _target_id(target) not in seen
            ]

            if not new_targets:
                return {
                    "status": STATUS_INCOMPLETE,
                    "rounds": round_number,
                    "assessment": assessment,
                    "assessment_status": "no_new_follow_up_targets",
                    "reason": (
                        "All follow-up targets had already been examined."
                    ),
                    "diagnostic_code": (
                        "DEEP_SEARCH_FOLLOW_UP_TARGETS_REPEATED"
                    ),
                }

            logger.info(
                "deep_search_follow_up_scheduled",
                extra={
                    "round": round_number,
                    "follow_up_target_count": len(new_targets),
                },
            )

            return {
                "status": STATUS_RUNNING,
                "rounds": round_number,
                "assessment": assessment,
                "assessment_status": STATUS_RUNNING,
                "next_targets": new_targets,
                "retrieval_query": assessment.get("follow_up_query"),
            }

        if assessment_status == STATUS_COMPLETE:
            if not isinstance(diagnosis, str) or not diagnosis.strip():
                return {
                    "status": STATUS_INCOMPLETE,
                    "rounds": round_number,
                    "assessment": assessment,
                    "assessment_status": "invalid_complete_result",
                    "reason": (
                        "Assessment reported completion without a diagnosis."
                    ),
                    "diagnostic_code": (
                        "DEEP_SEARCH_COMPLETION_WITHOUT_DIAGNOSIS"
                    ),
                }

            if not evidence:
                return {
                    "status": STATUS_INCOMPLETE,
                    "rounds": round_number,
                    "assessment": assessment,
                    "assessment_status": "evidence_missing",
                    "reason": (
                        "Assessment reported completion without supporting "
                        "evidence."
                    ),
                    "diagnostic_code": (
                        "DEEP_SEARCH_COMPLETION_WITHOUT_EVIDENCE"
                    ),
                }

            logger.info(
                "deep_search_assessment_completed",
                extra={
                    "round": round_number,
                    "evidence_count": len(evidence),
                    "confidence": assessment.get("confidence"),
                },
            )

            return {
                "status": STATUS_COMPLETE,
                "rounds": round_number,
                "assessment": assessment,
                "assessment_status": STATUS_COMPLETE,
                "diagnosis": diagnosis.strip(),
                "confidence": assessment.get("confidence"),
                "evidence": evidence,
                "reason": assessment.get("reason"),
                "next_targets": [],
            }

        normalized = (
            STATUS_INCOMPLETE
            if assessment_status == STATUS_INCOMPLETE
            else STATUS_UNAVAILABLE
        )

        return {
            "status": normalized,
            "rounds": round_number,
            "assessment": assessment,
            "assessment_status": assessment_status,
            "reason": (
                assessment.get("reason")
                or "Assessment could not establish a supported diagnosis."
            ),
            "diagnostic_code": (
                "DEEP_SEARCH_ASSESSMENT_NOT_COMPLETE"
            ),
        }

    def _finalize(
        self,
        state: DeepSearchState,
    ) -> dict[str, Any]:
        """Create the stable result consumed by the search service."""
        status = state.get("status", STATUS_UNAVAILABLE)

        if status not in {
            STATUS_COMPLETE,
            STATUS_INCOMPLETE,
            STATUS_UNAVAILABLE,
        }:
            status = STATUS_UNAVAILABLE

        assessment = state.get("assessment", {})
        if not isinstance(assessment, Mapping):
            assessment = {}

        diagnosis = state.get("diagnosis") or assessment.get("diagnosis")
        evidence = (
            state.get("evidence")
            or assessment.get("evidence")
            or []
        )
        if not isinstance(evidence, list):
            evidence = []

        if status == STATUS_COMPLETE and (
            not isinstance(diagnosis, str)
            or not diagnosis.strip()
            or not evidence
        ):
            status = STATUS_INCOMPLETE

        confidence = state.get("confidence")
        if confidence is None:
            confidence = assessment.get("confidence")

        result = {
            "status": status,
            "intent": _normalize_intent(
                state.get("intent", INTENT_FIX_BUG)
            ),
            "repo_name": state.get("repo_name"),
            "collection_name": self._resolve_collection(state),
            "diagnosis": (
                diagnosis if status == STATUS_COMPLETE else None
            ),
            "confidence": (
                confidence if status == STATUS_COMPLETE else None
            ),
            "evidence": (
                evidence if status == STATUS_COMPLETE else []
            ),
            "retrieved_chunks": state.get("retrieved_chunks", []),
            "searched_targets": state.get("seen_target_ids", []),
            "missing_targets": state.get("missing_targets", []),
            "rounds": state.get("rounds", 0),
            "reason": state.get("reason"),
            "diagnostic_code": state.get("diagnostic_code"),
            "graph_metadata": state.get("graph_metadata", {}),
            "assessment_status": state.get("assessment_status"),
        }

        if status != STATUS_COMPLETE:
            logger.warning(
                f"[DeepSearch] Finalized with status='{status}' (rounds={result['rounds']}): {result.get('reason')} "
                f"(diagnostic_code={result.get('diagnostic_code')})."
            )
        else:
            logger.info(
                f"[DeepSearch] Finalized with STATUS_COMPLETE (rounds={result['rounds']}, "
                f"confidence={result.get('confidence')}, evidence_count={len(result['evidence'])})."
            )

        return {"final_result": result, "status": status}

    def _terminal_result(
        self,
        state: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Return a safe result for failures before graph finalization."""
        return {
            "status": state.get("status", STATUS_UNAVAILABLE),
            "intent": _normalize_intent(
                state.get("intent", INTENT_FIX_BUG)
            ),
            "repo_name": state.get("repo_name"),
            "collection_name": self._resolve_collection(state),
            "diagnosis": None,
            "confidence": None,
            "evidence": [],
            "retrieved_chunks": state.get("retrieved_chunks", []),
            "searched_targets": state.get("seen_target_ids", []),
            "missing_targets": state.get("missing_targets", []),
            "rounds": state.get("rounds", 0),
            "reason": (
                state.get("reason")
                or "Deep Search could not establish a supported diagnosis."
            ),
            "diagnostic_code": state.get("diagnostic_code"),
            "graph_metadata": state.get("graph_metadata", {}),
            "assessment_status": state.get("assessment_status"),
        }


class DeepSearchStage:
    """Pipeline adapter that invokes Deep Search only when selected."""

    def __init__(
        self,
        llm_service: Any = None,
        hybrid_search: Any = None,
        workflow: Optional[DeepSearchWorkflow] = None,
        source_provider: Optional[Any] = None,
        search_adapter: Any = None,
        assessment_adapter: Any = None,
        max_rounds: int = MAX_INVESTIGATION_ROUNDS,
        max_graph_depth: int = MAX_GRAPH_DEPTH,
        max_targets: int = MAX_TARGETS,
    ) -> None:
        self.llm_service = llm_service
        self.hybrid_search = hybrid_search

        resolved_search_adapter = (
            search_adapter
            if search_adapter is not None
            else hybrid_search
        )

        # The stage owns asynchronous source acquisition. The workflow
        # receives source_files in its state and remains synchronous.
        self.workflow = workflow or DeepSearchWorkflow(
            source_provider=None,
            search_adapter=resolved_search_adapter,
            assessment_adapter=assessment_adapter,
            max_rounds=max_rounds,
            max_graph_depth=max_graph_depth,
            max_targets=max_targets,
        )

        self.source_provider = (
            source_provider
            or getattr(self.workflow, "source_provider", None)
            or provide_source_files
        )

        logger.info(
            "deep_search_stage_initialized",
            extra={
                "workflow_injected": workflow is not None,
                "source_provider_configured": (
                    self.source_provider is not None
                ),
                "source_provider_async": inspect.iscoroutinefunction(
                    self.source_provider
                ),
                "search_adapter_configured": (
                    resolved_search_adapter is not None
                ),
                "assessment_adapter_configured": (
                    assessment_adapter is not None
                ),
                "max_rounds": self.workflow.max_rounds,
                "max_graph_depth": self.workflow.max_graph_depth,
                "max_targets": self.workflow.max_targets,
            },
        )

    @staticmethod
    def _context_value(
        context: Any,
        *names: str,
    ) -> Any:
        if isinstance(context, Mapping):
            for name in names:
                value = context.get(name)
                if value is not None:
                    return value
            return None

        for name in names:
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
        if isinstance(context, dict):
            context[name] = value
            return

        try:
            setattr(context, name, value)
        except Exception as exc:
            raise RuntimeError(
                f"Unable to set context field '{name}'."
            ) from exc

    async def execute(self, context: Any) -> Any:
        """
        Acquire source asynchronously and run the synchronous workflow
        without blocking the event loop.

        Unselected requests continue through the normal search flow.
        """
        raw_intent = self._context_value(context, "intent")
        intent = _normalize_intent(raw_intent)

        parameters = self._context_value(
            context,
            "intent_parameters",
        )
        if not isinstance(parameters, Mapping):
            parameters = {}

        requested = (
            parameters.get("deep_search_requested") is True
            or self._context_value(
                context,
                "deep_search_requested",
            ) is True
        )

        if intent != INTENT_FIX_BUG or not requested:
            logger.info(
                "deep_search_stage_skipped",
                extra={
                    "intent": intent,
                    "deep_search_requested": requested,
                },
            )
            return context

        repo_name = self._context_value(context, "repo_name")

        collection_name = self._context_value(
            context,
            "qdrant_collection",
            "collection_name",
            "resolved_collection",
            "selected_collection",
        )

        collection_selection = self._context_value(
            context,
            "collection_selection",
        )

        query = self._context_value(
            context,
            "query",
            "search_query",
            "user_query",
        )
        if not query:
            query = parameters.get("query")

        source_files = self._context_value(context, "source_files")
        request_id = self._context_value(context, "request_id")

        state: DeepSearchState = {
            "query": str(query or ""),
            "intent": intent,
            "deep_search_requested": True,
            "repo_name": repo_name,
            "collection_name": collection_name,
            "collection_selection": collection_selection,
            "source_type": self._context_value(context, "source_type"),
            "source_location": self._context_value(
                context,
                "source_location",
            ),
            "rounds": 0,
            "max_rounds": self.workflow.max_rounds,
            "max_graph_depth": self.workflow.max_graph_depth,
            "max_targets": self.workflow.max_targets,
            "status": STATUS_RUNNING,
        }

        if source_files is not None:
            state["source_files"] = source_files

        logger.info(
            "deep_search_stage_execution_started",
            extra={
                "request_id": request_id,
                "intent": intent,
                "deep_search_requested": requested,
                "repo_name": repo_name,
                "collection_name": collection_name,
                "source_files_provided": isinstance(
                    source_files, Mapping
                ),
                "source_provider_configured": (
                    self.source_provider is not None
                ),
            },
        )

        result: dict[str, Any]

        try:
            # Acquire a snapshot only when one has not already been supplied.
            if not isinstance(source_files, Mapping) or not source_files:
                provider = self.source_provider

                if provider is None:
                    raise DeepSearchSourceError(
                        "No source files were supplied and no source "
                        "provider is configured."
                    )

                if inspect.iscoroutinefunction(provider):
                    acquired = await provider(dict(state))
                else:
                    # Do not block the application's event loop for
                    # custom synchronous providers.
                    acquired = await asyncio.to_thread(
                        provider,
                        dict(state),
                    )

                    # Handle a synchronous wrapper returning an awaitable.
                    if inspect.isawaitable(acquired):
                        acquired = await acquired

                if not isinstance(acquired, Mapping) or not acquired:
                    raise DeepSearchSourceError(
                        "Source acquisition returned no usable source files."
                    )

                state["source_files"] = acquired

                logger.info(
                    "deep_search_source_acquisition_completed",
                    extra={
                        "request_id": request_id,
                        "repo_name": repo_name,
                        "collection_name": collection_name,
                        "source_file_count": len(acquired),
                    },
                )

            # Source is ready before the synchronous LangGraph workflow
            # runs in a worker thread. No async Qdrant operation occurs
            # inside that worker thread.
            result_value = await asyncio.to_thread(
                self.workflow.run,
                state,
            )

            if not isinstance(result_value, Mapping):
                raise TypeError(
                    "Deep Search workflow returned a non-mapping result."
                )

            result = dict(result_value)

        except DeepSearchSourceError as exc:
            logger.error(
                f"[DeepSearch] Source acquisition failed for repo '{repo_name}': {exc}"
            )
            logger.warning(
                "deep_search_source_acquisition_unavailable",
                extra={
                    "request_id": request_id,
                    "repo_name": repo_name,
                    "collection_name": collection_name,
                    "error": str(exc),
                },
            )

            result = {
                "status": STATUS_UNAVAILABLE,
                "intent": INTENT_FIX_BUG,
                "repo_name": repo_name,
                "collection_name": collection_name,
                "diagnosis": None,
                "confidence": None,
                "evidence": [],
                "retrieved_chunks": [],
                "searched_targets": [],
                "missing_targets": [],
                "rounds": 0,
                "reason": str(exc),
                "diagnostic_code": (
                    "DEEP_SEARCH_SOURCE_ACQUISITION_FAILED"
                ),
            }

        except Exception as exc:
            logger.error(
                f"[DeepSearch] Unexpected error in DeepSearchStage for repo '{repo_name}': {exc}",
                exc_info=True,
            )
            result = {
                "status": STATUS_UNAVAILABLE,
                "intent": INTENT_FIX_BUG,
                "repo_name": repo_name,
                "collection_name": collection_name,
                "diagnosis": None,
                "confidence": None,
                "evidence": [],
                "retrieved_chunks": [],
                "searched_targets": [],
                "missing_targets": [],
                "rounds": 0,
                "reason": (
                    "Deep Search stage execution failed. "
                    "Inspect the server traceback using the request ID."
                ),
                "diagnostic_code": "DEEP_SEARCH_STAGE_EXCEPTION",
            }

        self._set_context_value(
            context,
            "deep_search_result",
            result,
        )

        # Preserve the existing Deep Search early-exit contract.
        self._set_context_value(
            context,
            "early_exit",
            "DEEP_SEARCH_COMPLETE",
        )

        logger.info(
            "deep_search_stage_execution_completed",
            extra={
                "request_id": request_id,
                "repo_name": repo_name,
                "collection_name": collection_name,
                "status": result.get("status"),
                "diagnostic_code": result.get("diagnostic_code"),
                "diagnosis_present": bool(result.get("diagnosis")),
                "retrieved_chunk_count": _safe_count(
                    result.get("retrieved_chunks")
                ),
                "searched_target_count": _safe_count(
                    result.get("searched_targets")
                ),
                "rounds": result.get("rounds", 0),
            },
        )

        return context
