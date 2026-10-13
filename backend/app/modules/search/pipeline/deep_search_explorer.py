
"""
RepoLens Deep Search dependency explorer.

Location:
    app/modules/search/pipeline/deep_search_explorer.py

Responsibilities:
    - Select initial graph targets using the user's bug query.
    - Expand targets through verified dependency relationships.
    - Return bounded, repository-local investigation targets.
    - Preserve evidence explaining why each target was selected.

This module does not:
    - Call an LLM.
    - Retrieve code from Qdrant.
    - Modify repository files.
    - Invent unresolved dependencies.
"""

from __future__ import annotations

import re

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional

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

    Query matching is used only to select investigation starting points.
    Relationships between files are taken from the dependency graph, not
    inferred from matching filenames or shared words.
    """

    DEFAULT_EDGE_KINDS = {
        "imports",
        "imports_symbol",
        "calls",
        "defines",
        "references_attribute",
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

        self.max_depth = max_depth
        self.max_targets = max_targets

    def explore(
        self,
        *,
        query: str,
        graph: DependencyGraph,
        initial_targets: Optional[Iterable[str]] = None,
        previous_targets: Optional[Iterable[str]] = None,
    ) -> ExplorationResult:
        """
        Explore a graph using the query and optional prior investigation IDs.

        Args:
            query:
                Original bug query or a bounded follow-up query.
            graph:
                Graph built from the selected repository source.
            initial_targets:
                Optional verified graph node IDs identified by another stage.
            previous_targets:
                Optional nodes already investigated. These are deprioritized
                so a subsequent round can investigate new related nodes.
        """
        if not isinstance(query, str) or not query.strip():
            return ExplorationResult(
                targets=(),
                unresolved_references=(),
                truncated=False,
                reason="The bug query is empty.",
            )

        previous = set(previous_targets or ())
        seeds: list[tuple[GraphNode, str, tuple[str, ...]]] = []

        # Explicit IDs must exist in this graph. Never accept a path or node
        # from another repository merely because its name looks similar.
        for node_id in initial_targets or ():
            node = graph.nodes.get(node_id)
            if node is not None:
                seeds.append(
                    (
                        node,
                        "Provided by an earlier verified investigation stage.",
                        (),
                    )
                )

        if not seeds:
            seeds.extend(self._select_query_seeds(query, graph))

        if not seeds:
            return ExplorationResult(
                targets=(),
                unresolved_references=self._relevant_unresolved(query, graph),
                truncated=False,
                reason=(
                    "No graph node matched the query with sufficient "
                    "lexical evidence. Targeted retrieval is required to "
                    "identify a starting point."
                ),
            )

        queue: list[tuple[str, int, str, tuple[str, ...]]] = []
        visited: set[str] = set()
        selected: list[InvestigationTarget] = []

        for node, reason, evidence in seeds:
            if node.id in visited:
                continue

            visited.add(node.id)
            queue.append((node.id, 0, reason, evidence))

        while queue and len(selected) < self.max_targets:
            node_id, depth, reason, evidence = queue.pop(0)
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

            neighbors = self._neighbors(graph, node_id)

            for neighbor, edge_kind, edge_evidence in neighbors:
                if neighbor.id in visited:
                    continue

                visited.add(neighbor.id)

                next_reason = (
                    f"Connected through verified '{edge_kind}' relationship "
                    f"from {node.path}:{node.line or '?'}."
                )

                queue.append(
                    (
                        neighbor.id,
                        depth + 1,
                        next_reason,
                        (edge_evidence,) if edge_evidence else (),
                    )
                )

        return ExplorationResult(
            targets=tuple(selected),
            unresolved_references=self._relevant_unresolved(query, graph),
            truncated=bool(queue),
            reason=(
                "Investigation targets selected from verified graph "
                "relationships."
                if selected
                else (
                    "All matching nodes were already investigated; "
                    "no new targets were selected."
                )
            ),
        )

    def _select_query_seeds(
        self,
        query: str,
        graph: DependencyGraph,
    ) -> list[tuple[GraphNode, str, tuple[str, ...]]]:
        """
        Select exact identifier/path matches before weaker token matches.

        This is only seed selection; lexical similarity does not create
        dependency edges or establish a bug diagnosis.
        """
        tokens = self._query_tokens(query)
        if not tokens:
            return []

        exact_matches: list[tuple[GraphNode, str, tuple[str, ...]]] = []
        token_matches: list[
            tuple[int, GraphNode, str, tuple[str, ...]]
        ] = []

        normalized_query = query.replace("\\", "/").lower()

        for node in graph.nodes.values():
            if node.kind not in {
                "file",
                "python_file",
                "template_file",
                "class",
                "interface",
                "type",
                "property",
                "function",
                "method",
                "attribute_reference",
                "template_attribute_reference",
            }:
                continue

            path = node.path.lower()
            name = node.name.lower()
            metadata_text = " ".join(
                str(value).lower()
                for value in node.metadata.values()
                if isinstance(value, (str, int, float))
            )

            if path in normalized_query or name in normalized_query:
                exact_matches.append(
                    (
                        node,
                        "Exact path or symbol name appears in the bug query.",
                        (node.path, node.name),
                    )
                )
                continue

            searchable = f"{path} {name} {metadata_text}"
            matched_tokens = [
                token
                for token in tokens
                if token in searchable.split()
            ]

            if matched_tokens:
                score = len(matched_tokens)
                token_matches.append(
                    (
                        score,
                        node,
                        "Query identifiers overlap with this graph node.",
                        tuple(matched_tokens),
                    )
                )

        if exact_matches:
            return exact_matches[: self.max_targets]

        # Keep only the best lexical matches. Ties are deterministic.
        token_matches.sort(
            key=lambda item: (
                -item[0],
                item[1].path,
                item[1].line or 0,
                item[1].id,
            )
        )

        if not token_matches:
            return []

        best_score = token_matches[0][0]

        # Avoid treating weak, generic one-token overlap as reliable evidence.
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
        neighbors: list[tuple[GraphNode, str, str]] = []

        for edge in graph.outgoing(node_id, self.DEFAULT_EDGE_KINDS):
            target = graph.nodes.get(edge.target)
            if target is not None:
                neighbors.append(
                    (target, edge.kind, edge.evidence)
                )

        for edge in graph.incoming(node_id, self.DEFAULT_EDGE_KINDS):
            source = graph.nodes.get(edge.source)
            if source is not None:
                neighbors.append(
                    (source, edge.kind, edge.evidence)
                )

        neighbors.sort(
            key=lambda item: (
                item[0].path,
                item[0].line or 0,
                item[0].id,
            )
        )

        return neighbors

    @staticmethod
    def _query_tokens(query: str) -> list[str]:
        # Preserve useful identifiers such as appointment_date and
        # Appointment while excluding very short generic terms.
        tokens = re.findall(
            r"[A-Za-z_][A-Za-z0-9_]*",
            query.lower(),
        )

        stop_words = {
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
        }

        return list(
            dict.fromkeys(
                token
                for token in tokens
                if len(token) >= 3 and token not in stop_words
            )
        )

    @staticmethod
    def _relevant_unresolved(
        query: str,
        graph: DependencyGraph,
    ) -> tuple[dict[str, Any], ...]:
        """
        Return unresolved references with query identifier overlap.

        These references are investigation clues, not verified relationships.
        """
        query_tokens = set(
            DeepSearchExplorer._query_tokens(query)
        )

        results: list[dict[str, Any]] = []

        for item in graph.unresolved:
            expr = getattr(item, "expression", getattr(item, "name", ""))
            searchable = (
                f"{item.path} {expr} {item.kind}"
            ).lower()

            matched = sorted(
                token
                for token in query_tokens
                if token in searchable
            )

            if matched:
                results.append(
                    {
                        "path": item.path,
                        "line": item.line,
                        "kind": item.kind,
                        "expression": expr,
                        "reason": item.reason,
                        "matched_query_tokens": matched,
                    }
                )

        return tuple(results)
