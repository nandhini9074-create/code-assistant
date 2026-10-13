
"""
app/modules/search/pipeline/deep_search_explorer.py

Deterministic dependency explorer for RepoLens Deep Search.

Responsibilities:
    - Select initial graph targets using the user's bug query.
    - Expand targets through verified dependency relationships.
    - Return bounded, repository-local investigation targets.
    - Preserve evidence explaining why each target was selected.
    - Surface relevant unresolved references without treating them as
      confirmed dependencies.
    - Support bounded subsequent investigation rounds.

This module does not:
    - Call an LLM.
    - Retrieve code from Qdrant.
    - Access the filesystem.
    - Modify repository files.
    - Invent unresolved dependencies.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from app.modules.search.pipeline.dependency_graph import (
    DependencyGraph,
    GraphNode,
)

DEFAULT_MAX_DEPTH = 3
DEFAULT_MAX_TARGETS = 12


@dataclass(frozen=True)
class InvestigationTarget:
    """A graph node selected for targeted code investigation."""

    node_id: str
    path: str
    name: str
    kind: str
    depth: int
    reason: str
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExplorationResult:
    """Bounded targets selected from a dependency graph."""

    targets: tuple[InvestigationTarget, ...]
    unresolved_references: tuple[dict[str, Any], ...]
    truncated: bool
    reason: str


class DeepSearchExplorer:
    """
    Select relevant nodes and expand their verified graph relationships.

    Lexical matching selects starting points only. Relationships between
    nodes must already exist as graph edges created by dependency_graph.py.
    """

    # These edge types are emitted by the current dependency_graph.py.
    #
    # Imports are traversed through:
    # file -> import -> imported file/symbol
    #
    # Calls are traversed through:
    # containing symbol -> call -> target definition
    #
    # Template relationships are traversed through:
    # render call -> template reference
    DEFAULT_EDGE_KINDS = {
        "defines",
        "imports",
        "imports_module",
        "imports_symbol",
        "calls",
        "contains_call",
        "references_attribute",
        "contains_template_reference",
        "renders_template",
        "supplies_template_context",
    }

    SEARCHABLE_NODE_KINDS = {
        "python_file",
        "template_file",
        "file",
        "class",
        "function",
        "method",
        "attribute_reference",
        "template_attribute_reference",
        "call",
    }

    STOP_WORDS = {
        "the",
        "and",
        "for",
        "from",
        "with",
        "this",
        "that",
        "when",
        "where",
        "what",
        "how",
        "has",
        "have",
        "error",
        "bug",
        "fix",
        "issue",
        "please",
        "does",
        "not",
        "was",
        "were",
        "are",
        "is",
        "into",
        "using",
        "used",
        "use",
        "unable",
        "cannot",
        "could",
        "would",
        "should",
    }

    def __init__(
        self,
        *,
        max_depth: int = DEFAULT_MAX_DEPTH,
        max_targets: int = DEFAULT_MAX_TARGETS,
    ) -> None:
        if max_depth < 0:
            raise ValueError("max_depth cannot be negative.")

        if max_targets <= 0:
            raise ValueError("max_targets must be positive.")

        self.max_depth = int(max_depth)
        self.max_targets = int(max_targets)

    def explore(
        self,
        *,
        query: str,
        graph: DependencyGraph,
        initial_targets: Optional[Iterable[str]] = None,
        previous_targets: Optional[Iterable[str]] = None,
    ) -> ExplorationResult:
        """
        Select and expand targets from a dependency graph.

        Args:
            query:
                Original bug query or a bounded follow-up query.
            graph:
                Graph built from the selected repository's source snapshot.
            initial_targets:
                Optional graph node IDs verified by an earlier stage.
            previous_targets:
                Optional node IDs already investigated in prior rounds.

        Returns:
            An ExplorationResult containing bounded targets and relevant
            unresolved references.
        """
        if not isinstance(query, str) or not query.strip():
            return ExplorationResult(
                targets=(),
                unresolved_references=(),
                truncated=False,
                reason="The bug query is empty.",
            )

        if not isinstance(graph, DependencyGraph):
            return ExplorationResult(
                targets=(),
                unresolved_references=(),
                truncated=False,
                reason="A valid dependency graph was not supplied.",
            )

        previous = {
            node_id
            for node_id in (previous_targets or ())
            if isinstance(node_id, str)
        }

        seeds: list[
            tuple[GraphNode, str, tuple[str, ...]]
        ] = []

        # Accept only IDs that exist in this exact graph.
        for node_id in initial_targets or ():
            if not isinstance(node_id, str):
                continue

            node = graph.nodes.get(node_id)
            if node is not None:
                seeds.append(
                    (
                        node,
                        "Provided by an earlier verified investigation stage.",
                        (f"verified_node_id:{node.id}",),
                    )
                )

        if not seeds:
            seeds = self._select_query_seeds(query, graph)

        if not seeds:
            return ExplorationResult(
                targets=(),
                unresolved_references=self._relevant_unresolved(
                    query,
                    graph,
                ),
                truncated=False,
                reason=(
                    "No graph node matched the query with sufficient "
                    "lexical evidence. A separate targeted retrieval stage "
                    "must identify a starting point."
                ),
            )

        # Breadth-first traversal ensures shallower dependencies are
        # considered before deeper relationships.
        queue: deque[
            tuple[str, int, str, tuple[str, ...]]
        ] = deque()

        visited: set[str] = set()
        selected: list[InvestigationTarget] = []

        for node, reason, evidence in seeds:
            if node.id in visited:
                continue

            visited.add(node.id)
            queue.append((node.id, 0, reason, evidence))

        truncated = False

        while queue:
            # Do not silently discard unprocessed nodes when the target
            # limit has been reached.
            if len(selected) >= self.max_targets:
                truncated = True
                break

            node_id, depth, reason, evidence = queue.popleft()
            node = graph.nodes.get(node_id)

            if node is None:
                continue

            if node_id not in previous:
                selected.append(
                    InvestigationTarget(
                        node_id=node.id,
                        path=node.path,
                        name=node.name,
                        kind=node.kind,
                        depth=depth,
                        reason=reason,
                        evidence=evidence,
                    )
                )

            if depth >= self.max_depth:
                continue

            for neighbor, edge_kind, edge_evidence in self._neighbors(
                graph,
                node_id,
            ):
                if neighbor.id in visited:
                    continue

                visited.add(neighbor.id)

                next_reason = (
                    f"Connected through verified '{edge_kind}' "
                    f"relationship from {node.path}:{node.line or '?'}."
                )

                next_evidence = (
                    (edge_evidence,)
                    if edge_evidence
                    else (
                        f"graph_edge:{node_id}->{neighbor.id}:{edge_kind}",
                    )
                )

                queue.append(
                    (
                        neighbor.id,
                        depth + 1,
                        next_reason,
                        next_evidence,
                    )
                )

        # A queue can contain nodes after the target cap is reached.
        if queue:
            truncated = True

        if selected:
            reason = (
                "Investigation targets selected from query matches and "
                "verified graph relationships."
            )
        elif previous:
            reason = (
                "Matching graph nodes were already investigated; "
                "no new targets were selected."
            )
        else:
            reason = (
                "No new investigation targets could be selected."
            )

        return ExplorationResult(
            targets=tuple(selected),
            unresolved_references=self._relevant_unresolved(query, graph),
            truncated=truncated,
            reason=reason,
        )

    def _select_query_seeds(
        self,
        query: str,
        graph: DependencyGraph,
    ) -> list[tuple[GraphNode, str, tuple[str, ...]]]:
        """
        Select exact path/symbol matches before weaker token matches.

        Query matching never creates dependency edges or proves a diagnosis.
        """
        tokens = self._query_tokens(query)
        if not tokens:
            return []

        exact_matches: list[
            tuple[GraphNode, str, tuple[str, ...]]
        ] = []

        token_matches: list[
            tuple[int, GraphNode, str, tuple[str, ...]]
        ] = []

        normalized_query = self._normalize_search_text(query)

        for node in graph.nodes.values():
            if node.kind not in self.SEARCHABLE_NODE_KINDS:
                continue

            path = node.path.lower()
            name = node.name.lower()

            metadata_values = [
                str(value).lower()
                for value in node.metadata.values()
                if isinstance(value, (str, int, float))
            ]

            metadata_text = " ".join(metadata_values)

            normalized_path = self._normalize_search_text(path)
            normalized_name = self._normalize_search_text(name)

            # Prefer a full path or identifier explicitly supplied by the
            # user. Exclude empty identifiers.
            if (
                normalized_path
                and normalized_path in normalized_query
            ) or (
                normalized_name
                and len(normalized_name) >= 3
                and normalized_name in normalized_query
            ):
                exact_matches.append(
                    (
                        node,
                        "Exact path or symbol name appears in the bug query.",
                        (node.path, node.name),
                    )
                )
                continue

            searchable = self._normalize_search_text(
                f"{path} {name} {metadata_text}"
            )

            searchable_tokens = set(self._query_tokens(searchable))

            matched_tokens = tuple(
                token for token in tokens if token in searchable_tokens
            )

            if matched_tokens:
                token_matches.append(
                    (
                        len(matched_tokens),
                        node,
                        "Query identifiers overlap with this graph node.",
                        matched_tokens,
                    )
                )

        if exact_matches:
            exact_matches.sort(
                key=lambda item: (
                    item[0].path,
                    item[0].line or 0,
                    item[0].id,
                )
            )
            return exact_matches[: self.max_targets]

        if not token_matches:
            return []

        token_matches.sort(
            key=lambda item: (
                -item[0],
                item[1].path,
                item[1].line or 0,
                item[1].id,
            )
        )

        best_score = token_matches[0][0]

        # Avoid selecting graph nodes from only one generic word when the
        # query contains multiple meaningful identifiers.
        if best_score < 2 and len(tokens) > 1:
            return []

        return [
            (node, reason, evidence)
            for score, node, reason, evidence in token_matches
            if score == best_score
        ][: self.max_targets]

    def _neighbors(
        self,
        graph: DependencyGraph,
        node_id: str,
    ) -> list[tuple[GraphNode, str, str]]:
        """
        Return neighbors connected through supported graph edge types.

        dependency_graph.py exposes outgoing(node_id) and incoming(node_id)
        without edge filters. Edge evidence is stored in edge.metadata.
        """
        neighbors: list[tuple[GraphNode, str, str]] = []

        for edge in graph.outgoing(node_id):
            if edge.kind not in self.DEFAULT_EDGE_KINDS:
                continue

            target = graph.nodes.get(edge.target)
            if target is None:
                continue

            evidence = self._edge_evidence(edge.metadata)
            neighbors.append((target, edge.kind, evidence))

        for edge in graph.incoming(node_id):
            if edge.kind not in self.DEFAULT_EDGE_KINDS:
                continue

            source = graph.nodes.get(edge.source)
            if source is None:
                continue

            evidence = self._edge_evidence(edge.metadata)
            neighbors.append((source, edge.kind, evidence))

        # Deduplicate the same neighbor reached by the same edge type.
        unique: dict[
            tuple[str, str],
            tuple[GraphNode, str, str],
        ] = {}

        for node, edge_kind, evidence in neighbors:
            key = (node.id, edge_kind)
            existing = unique.get(key)

            if existing is None or (
                not existing[2] and evidence
            ):
                unique[key] = (node, edge_kind, evidence)

        return sorted(
            unique.values(),
            key=lambda item: (
                item[0].path,
                item[0].line or 0,
                item[0].id,
                item[1],
            ),
        )

    @staticmethod
    def _edge_evidence(metadata: Any) -> str:
        """Extract existing edge evidence without inventing any."""
        if not isinstance(metadata, dict):
            return ""

        evidence = metadata.get("evidence")

        if isinstance(evidence, str):
            return evidence.strip()

        # Other metadata can describe the relationship but is not labeled
        # as formal evidence. Do not represent it as verified evidence text.
        return ""

    @staticmethod
    def _normalize_search_text(value: str) -> str:
        """
        Normalize identifiers and paths for robust lexical comparison.

        Separators are normalized to spaces so identifiers such as
        `appointment_date` and paths such as `templates/appointments.html`
        can be matched consistently.
        """
        value = value.replace("\\", "/").lower()
        return re.sub(r"[^a-z0-9_./]+", " ", value).strip()

    @classmethod
    def _query_tokens(cls, query: str) -> list[str]:
        """
        Extract identifiers and useful words from a query.

        Underscore-containing identifiers are kept intact, so
        `appointment_date` remains a single token.
        """
        tokens = re.findall(
            r"[a-zA-Z_][a-zA-Z0-9_]*",
            query.lower(),
        )

        return list(
            dict.fromkeys(
                token
                for token in tokens
                if len(token) >= 3 and token not in cls.STOP_WORDS
            )
        )

    @classmethod
    def _relevant_unresolved(
        cls,
        query: str,
        graph: DependencyGraph,
    ) -> tuple[dict[str, Any], ...]:
        """
        Return unresolved references with query-token overlap.

        Unresolved references are investigation clues, not verified
        dependency relationships.
        """
        query_tokens = set(cls._query_tokens(query))
        results: list[dict[str, Any]] = []

        for item in graph.unresolved_references:
            searchable = cls._normalize_search_text(
                f"{item.path} {item.name} {item.kind} {item.reason}"
            )
            searchable_tokens = set(cls._query_tokens(searchable))

            matched = sorted(query_tokens & searchable_tokens)

            if not matched:
                continue

            results.append(
                {
                    "path": item.path,
                    "line": item.line,
                    "kind": item.kind,
                    "expression": item.name,
                    "reason": item.reason,
                    "matched_query_tokens": matched,
                }
            )

        results.sort(
            key=lambda item: (
                item["path"],
                item["line"] or 0,
                item["kind"],
                item["expression"],
            )
        )

        return tuple(results)
