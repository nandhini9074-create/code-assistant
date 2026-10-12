
"""
Deterministic dependency graph builder for RepoLens Deep Search.

Location:
    app/modules/search/pipeline/dependency_graph.py

Responsibilities:
    - Discover Python file imports and verified module dependencies.
    - Discover function, method, and class definitions.
    - Discover statically resolvable function calls.
    - Record attribute references in Python and common HTML/Jinja templates.
    - Preserve source locations and evidence for graph relationships.
    - Support bounded traversal for Deep Search.

Non-responsibilities:
    - No LLM calls.
    - No Qdrant calls.
    - No repository writes.
    - No repository identification or collection selection.
    - No guessing unresolved dependencies.

Input:
    A mapping of repository-relative file paths to their source text.

Important:
    This module deliberately does not read files from disk. The caller must
    supply source obtained through the application's existing read-only
    repository source mechanism.
"""

from __future__ import annotations

import ast
import re

from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping, Optional


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

DEFAULT_MAX_FILES = 500
DEFAULT_MAX_NODES = 10_000
DEFAULT_MAX_EDGES = 25_000
DEFAULT_MAX_DEPTH = 3

PYTHON_EXTENSIONS = {".py"}
TEMPLATE_EXTENSIONS = {".html", ".htm", ".jinja", ".j2", ".jinja2"}

IGNORED_DIRECTORIES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GraphNode:
    """One repository file, class, function, or attribute."""

    id: str
    kind: str
    path: str
    name: str
    line: Optional[int] = None
    end_line: Optional[int] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphEdge:
    """A verified relationship between two graph nodes."""

    source: str
    target: str
    kind: str
    source_path: str
    line: Optional[int]
    evidence: str


@dataclass(frozen=True)
class UnresolvedReference:
    """
    A reference that could not be linked to a verified graph target.

    Keeping unresolved references explicit prevents the graph from inventing
    relationships when imports, dynamic calls, or symbols cannot be resolved.
    """

    source: str
    path: str
    line: Optional[int]
    kind: str
    expression: str
    reason: str


@dataclass
class DependencyGraph:
    """Graph for a single repository source snapshot."""

    nodes: dict[str, GraphNode] = field(default_factory=dict)
    edges: list[GraphEdge] = field(default_factory=list)
    unresolved: list[UnresolvedReference] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_node(self, node: GraphNode) -> None:
        self.nodes.setdefault(node.id, node)

    def add_edge(self, edge: GraphEdge) -> None:
        # Both endpoints must already exist. This prevents dangling edges.
        if edge.source not in self.nodes or edge.target not in self.nodes:
            return

        if edge not in self.edges:
            self.edges.append(edge)

    def add_unresolved(self, item: UnresolvedReference) -> None:
        if item not in self.unresolved:
            self.unresolved.append(item)

    def outgoing(
        self,
        node_id: str,
        edge_kinds: Optional[set[str]] = None,
    ) -> list[GraphEdge]:
        return [
            edge
            for edge in self.edges
            if edge.source == node_id
            and (
                edge_kinds is None
                or edge.kind in edge_kinds
            )
        ]

    def incoming(
        self,
        node_id: str,
        edge_kinds: Optional[set[str]] = None,
    ) -> list[GraphEdge]:
        return [
            edge
            for edge in self.edges
            if edge.target == node_id
            and (
                edge_kinds is None
                or edge.kind in edge_kinds
            )
        ]

    def traverse(
        self,
        start_node_ids: Iterable[str],
        *,
        max_depth: int = DEFAULT_MAX_DEPTH,
        max_nodes: int = 100,
        edge_kinds: Optional[set[str]] = None,
        include_incoming: bool = True,
    ) -> list[GraphNode]:
        """
        Traverse verified graph relationships with strict bounds.

        The returned nodes include the starting nodes when those nodes exist.
        Both outgoing and incoming relationships are considered by default,
        allowing investigation of callers and dependencies.
        """
        if max_depth < 0 or max_nodes <= 0:
            return []

        queue: deque[tuple[str, int]] = deque()
        visited: set[str] = set()
        result: list[GraphNode] = []

        for node_id in start_node_ids:
            if node_id in self.nodes and node_id not in visited:
                visited.add(node_id)
                queue.append((node_id, 0))

        while queue and len(result) < max_nodes:
            node_id, depth = queue.popleft()
            node = self.nodes.get(node_id)

            if node is None:
                continue

            result.append(node)

            if depth >= max_depth:
                continue

            adjacent = self.outgoing(node_id, edge_kinds)

            if include_incoming:
                adjacent.extend(self.incoming(node_id, edge_kinds))

            for edge in adjacent:
                neighbor = (
                    edge.target
                    if edge.source == node_id
                    else edge.source
                )

                if neighbor in visited:
                    continue

                if neighbor not in self.nodes:
                    continue

                visited.add(neighbor)
                queue.append((neighbor, depth + 1))

        return result

    def to_dict(self) -> dict[str, Any]:
        """Serialize the graph into a JSON-compatible dictionary."""
        return {
            "nodes": {
                node_id: asdict(node)
                for node_id, node in self.nodes.items()
            },
            "edges": [asdict(edge) for edge in self.edges],
            "unresolved": [
                asdict(item) for item in self.unresolved
            ],
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Internal Python analysis records
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Definition:
    node_id: str
    kind: str
    path: str
    name: str
    qualified_name: str
    line: int
    end_line: int
    parent_class: Optional[str] = None


@dataclass(frozen=True)
class _ImportBinding:
    local_name: str
    module_name: str
    imported_name: Optional[str]
    line: int


@dataclass(frozen=True)
class _Reference:
    source_node_id: str
    path: str
    line: int
    kind: str
    expression: str


# ---------------------------------------------------------------------------
# Path and identifier helpers
# ---------------------------------------------------------------------------

def _normalize_path(path: str) -> str:
    """Normalize a repository-relative path without accessing the filesystem."""
    raw = str(path or "").replace("\\", "/").strip()
    parts = PurePosixPath(raw).parts

    if not raw or raw.startswith("/") or PurePosixPath(raw).is_absolute():
        raise ValueError(
            f"Expected a repository-relative path, received: {path!r}"
        )

    if any(part in {"..", "."} for part in parts):
        raise ValueError(
            f"Path traversal or ambiguous path is not allowed: {path!r}"
        )

    if not parts:
        raise ValueError("Repository-relative path cannot be empty.")

    return "/".join(parts)


def _is_ignored_path(path: str) -> bool:
    return any(
        part in IGNORED_DIRECTORIES
        for part in PurePosixPath(path).parts
    )


def _file_node_id(path: str) -> str:
    return f"file:{path}"


def _symbol_node_id(path: str, qualified_name: str) -> str:
    return f"symbol:{path}::{qualified_name}"


def _attribute_node_id(path: str, owner: str, attribute: str) -> str:
    return f"attribute:{path}::{owner}.{attribute}"


def _module_name_from_path(path: str) -> Optional[str]:
    """Convert a Python source path into a possible import module name."""
    if not path.endswith(".py"):
        return None

    parts = list(PurePosixPath(path).parts)

    if not parts:
        return None

    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][:-3]

    if not parts:
        return None

    if not all(part.isidentifier() for part in parts):
        return None

    return ".".join(parts)


def _module_candidates(module_name: str) -> tuple[str, ...]:
    """Possible source paths for a module import."""
    module_path = module_name.replace(".", "/")

    return (
        f"{module_path}.py",
        f"{module_path}/__init__.py",
    )


def _dotted_name(node: ast.AST) -> Optional[str]:
    """Resolve a syntactically dotted name without evaluating code."""
    if isinstance(node, ast.Name):
        return node.id

    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        if parent:
            return f"{parent}.{node.attr}"

    return None


def _node_line(node: ast.AST) -> int:
    return int(getattr(node, "lineno", 1))


def _node_end_line(node: ast.AST) -> int:
    return int(
        getattr(node, "end_lineno", getattr(node, "lineno", 1))
    )


# ---------------------------------------------------------------------------
# AST visitors
# ---------------------------------------------------------------------------

class _PythonFileAnalyzer(ast.NodeVisitor):
    """Extract definitions, imports, calls, and attribute references."""

    def __init__(
        self,
        *,
        path: str,
        tree: ast.AST,
        graph: DependencyGraph,
    ) -> None:
        self.path = path
        self.tree = tree
        self.graph = graph

        self.definitions: list[_Definition] = []
        self.imports: list[_ImportBinding] = []
        self.references: list[_Reference] = []

        self._scope: list[str] = []
        self._class_scope: list[str] = []
        self._scope_node_ids: list[str] = []

        self.file_id = _file_node_id(path)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qualified = ".".join([*self._scope, node.name])
        node_id = _symbol_node_id(self.path, qualified)

        self.graph.add_node(
            GraphNode(
                id=node_id,
                kind="class",
                path=self.path,
                name=node.name,
                line=node.lineno,
                end_line=_node_end_line(node),
                metadata={"qualified_name": qualified},
            )
        )

        self.graph.add_edge(
            GraphEdge(
                source=self.file_id,
                target=node_id,
                kind="defines",
                source_path=self.path,
                line=node.lineno,
                evidence=f"class {qualified}",
            )
        )

        self.definitions.append(
            _Definition(
                node_id=node_id,
                kind="class",
                path=self.path,
                name=node.name,
                qualified_name=qualified,
                line=node.lineno,
                end_line=_node_end_line(node),
                parent_class=self._class_scope[-1]
                if self._class_scope
                else None,
            )
        )

        self._scope.append(node.name)
        self._class_scope.append(qualified)
        self._scope_node_ids.append(node_id)

        for decorator in node.decorator_list:
            self.visit(decorator)

        for base in node.bases:
            self.visit(base)

        for keyword in node.keywords:
            self.visit(keyword.value)

        for statement in node.body:
            self.visit(statement)

        self._scope_node_ids.pop()
        self._class_scope.pop()
        self._scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        qualified = ".".join([*self._scope, node.name])
        node_id = _symbol_node_id(self.path, qualified)
        kind = "method" if self._class_scope else "function"

        self.graph.add_node(
            GraphNode(
                id=node_id,
                kind=kind,
                path=self.path,
                name=node.name,
                line=node.lineno,
                end_line=_node_end_line(node),
                metadata={
                    "qualified_name": qualified,
                    "async": isinstance(node, ast.AsyncFunctionDef),
                },
            )
        )

        parent_id = (
            self._scope_node_ids[-1]
            if self._scope_node_ids
            else self.file_id
        )

        self.graph.add_edge(
            GraphEdge(
                source=parent_id,
                target=node_id,
                kind="defines",
                source_path=self.path,
                line=node.lineno,
                evidence=f"definition {qualified}",
            )
        )

        self.definitions.append(
            _Definition(
                node_id=node_id,
                kind=kind,
                path=self.path,
                name=node.name,
                qualified_name=qualified,
                line=node.lineno,
                end_line=_node_end_line(node),
                parent_class=self._class_scope[-1]
                if self._class_scope
                else None,
            )
        )

        # Defaults and decorators execute in the surrounding scope.
        for decorator in node.decorator_list:
            self.visit(decorator)

        for default in node.args.defaults:
            self.visit(default)

        for default in node.args.kw_defaults:
            if default is not None:
                self.visit(default)

        self._scope.append(node.name)
        self._scope_node_ids.append(node_id)

        for statement in node.body:
            self.visit(statement)

        self._scope_node_ids.pop()
        self._scope.pop()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local_name = alias.asname or alias.name.split(".")[0]

            self.imports.append(
                _ImportBinding(
                    local_name=local_name,
                    module_name=alias.name,
                    imported_name=None,
                    line=node.lineno,
                )
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level:
            # Relative import resolution requires the package context.
            # It is resolved later only when a safe package candidate exists.
            module_name = "." * node.level + (node.module or "")
        else:
            module_name = node.module or ""

        for alias in node.names:
            if alias.name == "*":
                self.graph.add_unresolved(
                    UnresolvedReference(
                        source=self._current_scope_id(),
                        path=self.path,
                        line=node.lineno,
                        kind="wildcard_import",
                        expression=f"from {module_name} import *",
                        reason="Wildcard imports do not identify individual symbols.",
                    )
                )
                continue

            self.imports.append(
                _ImportBinding(
                    local_name=alias.asname or alias.name,
                    module_name=module_name,
                    imported_name=alias.name,
                    line=node.lineno,
                )
            )

    def visit_Call(self, node: ast.Call) -> None:
        expression = _dotted_name(node.func)

        if expression:
            self.references.append(
                _Reference(
                    source_node_id=self._current_scope_id(),
                    path=self.path,
                    line=_node_line(node),
                    kind="call",
                    expression=expression,
                )
            )
        else:
            self.graph.add_unresolved(
                UnresolvedReference(
                    source=self._current_scope_id(),
                    path=self.path,
                    line=_node_line(node),
                    kind="call",
                    expression=ast.dump(node.func, include_attributes=False),
                    reason="Dynamic call target cannot be resolved statically.",
                )
            )

        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        expression = _dotted_name(node)

        if expression:
            # Record attribute references, but do not infer which model object
            # an arbitrary variable represents.
            self.references.append(
                _Reference(
                    source_node_id=self._current_scope_id(),
                    path=self.path,
                    line=_node_line(node),
                    kind="attribute_reference",
                    expression=expression,
                )
            )

        self.generic_visit(node)

    def _current_scope_id(self) -> str:
        return (
            self._scope_node_ids[-1]
            if self._scope_node_ids
            else self.file_id
        )


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

class DependencyGraphBuilder:
    """
    Build a bounded dependency graph from repository source text.

    All supplied paths are normalized and treated as one repository snapshot.
    Pass only files belonging to the already-selected repository.
    """

    def __init__(
        self,
        *,
        max_files: int = DEFAULT_MAX_FILES,
        max_nodes: int = DEFAULT_MAX_NODES,
        max_edges: int = DEFAULT_MAX_EDGES,
    ) -> None:
        if max_files <= 0 or max_nodes <= 0 or max_edges <= 0:
            raise ValueError("Graph limits must be positive integers.")

        self.max_files = max_files
        self.max_nodes = max_nodes
        self.max_edges = max_edges

    def build(
        self,
        source_files: Mapping[str, str],
    ) -> DependencyGraph:
        """
        Build a graph from repository-relative paths and source contents.

        Files beyond max_files are not silently accepted: the returned graph
        records truncation in metadata. Invalid paths are rejected.
        """
        normalized: dict[str, str] = {}

        for original_path, source in source_files.items():
            path = _normalize_path(original_path)

            if _is_ignored_path(path):
                continue

            if not isinstance(source, str):
                raise TypeError(
                    f"Source content for {path!r} must be a string."
                )

            normalized[path] = source

        sorted_paths = sorted(normalized)
        truncated_files = len(sorted_paths) > self.max_files
        selected_paths = sorted_paths[: self.max_files]

        graph = DependencyGraph(
            metadata={
                "builder": "DependencyGraphBuilder",
                "source_file_count": len(selected_paths),
                "input_file_count": len(normalized),
                "truncated_files": truncated_files,
                "max_files": self.max_files,
                "max_nodes": self.max_nodes,
                "max_edges": self.max_edges,
                "supported_python_analysis": True,
                "supported_template_analysis": True,
            }
        )

        selected_sources = {
            path: normalized[path]
            for path in selected_paths
        }

        # First pass: create file nodes and parse Python source.
        analyzers: dict[str, _PythonFileAnalyzer] = {}

        for path, source in selected_sources.items():
            file_id = _file_node_id(path)
            suffix = PurePosixPath(path).suffix.lower()

            graph.add_node(
                GraphNode(
                    id=file_id,
                    kind="file",
                    path=path,
                    name=PurePosixPath(path).name,
                    metadata={"extension": suffix},
                )
            )

            if suffix in PYTHON_EXTENSIONS:
                try:
                    tree = ast.parse(source, filename=path)
                except (SyntaxError, ValueError) as exc:
                    graph.add_unresolved(
                        UnresolvedReference(
                            source=file_id,
                            path=path,
                            line=getattr(exc, "lineno", None),
                            kind="parse_error",
                            expression=str(exc),
                            reason="Python source could not be parsed.",
                        )
                    )
                    continue

                analyzer = _PythonFileAnalyzer(
                    path=path,
                    tree=tree,
                    graph=graph,
                )
                analyzer.visit(tree)
                analyzers[path] = analyzer

            elif suffix in TEMPLATE_EXTENSIONS:
                self._analyze_template(
                    path=path,
                    source=source,
                    graph=graph,
                )

        # Second pass: resolve imports, then resolve symbol calls and attributes.
        module_to_path = self._build_module_index(selected_paths)

        for path, analyzer in analyzers.items():
            self._resolve_imports(
                analyzer=analyzer,
                module_to_path=module_to_path,
                selected_paths=set(selected_paths),
                graph=graph,
            )

        if len(graph.nodes) <= self.max_nodes:
            self._resolve_references(analyzers, graph)
        else:
            graph.metadata["node_limit_reached_before_reference_resolution"] = True

        # Apply strict output limits. Keep edges only when both endpoints exist.
        if len(graph.nodes) > self.max_nodes:
            graph.metadata["truncated_nodes"] = (
                len(graph.nodes) - self.max_nodes
            )
            keep_ids = set(list(graph.nodes)[: self.max_nodes])
            graph.nodes = {
                node_id: node
                for node_id, node in graph.nodes.items()
                if node_id in keep_ids
            }

        if len(graph.edges) > self.max_edges:
            graph.metadata["truncated_edges"] = (
                len(graph.edges) - self.max_edges
            )
            graph.edges = graph.edges[: self.max_edges]

        graph.edges = [
            edge
            for edge in graph.edges
            if edge.source in graph.nodes
            and edge.target in graph.nodes
        ]

        graph.metadata["final_node_count"] = len(graph.nodes)
        graph.metadata["final_edge_count"] = len(graph.edges)
        graph.metadata["unresolved_count"] = len(graph.unresolved)

        return graph

    @staticmethod
    def _build_module_index(
        paths: Iterable[str],
    ) -> dict[str, str]:
        """
        Map importable Python module names to paths.

        Duplicate module names are intentionally excluded because the module
        target would otherwise be ambiguous.
        """
        candidates: dict[str, list[str]] = defaultdict(list)

        for path in paths:
            module_name = _module_name_from_path(path)
            if module_name:
                candidates[module_name].append(path)

        return {
            name: module_paths[0]
            for name, module_paths in candidates.items()
            if len(module_paths) == 1
        }

    def _resolve_imports(
        self,
        *,
        analyzer: _PythonFileAnalyzer,
        module_to_path: dict[str, str],
        selected_paths: set[str],
        graph: DependencyGraph,
    ) -> None:
        path = analyzer.path
        current_module = _module_name_from_path(path)
        current_package = (
            current_module
            if path.endswith("/__init__.py")
            else (
                current_module.rpartition(".")[0]
                if current_module
                else ""
            )
        )

        for binding in analyzer.imports:
            module_name = binding.module_name

            if module_name.startswith("."):
                relative_level = len(module_name) - len(
                    module_name.lstrip(".")
                )
                suffix = module_name[relative_level:]

                package_parts = current_package.split(".") if current_package else []

                if relative_level > len(package_parts) + 1:
                    resolved_module = None
                else:
                    keep_count = max(0, len(package_parts) - relative_level + 1)
                    base = package_parts[:keep_count]
                    if suffix:
                        base.extend(suffix.split("."))
                    resolved_module = ".".join(part for part in base if part)
            else:
                resolved_module = module_name

            target_path = (
                module_to_path.get(resolved_module)
                if resolved_module
                else None
            )

            # `from package import symbol` may refer to a submodule.
            if target_path is None and resolved_module and binding.imported_name:
                submodule = f"{resolved_module}.{binding.imported_name}"
                target_path = module_to_path.get(submodule)

            if target_path is None or target_path not in selected_paths:
                graph.add_unresolved(
                    UnresolvedReference(
                        source=_file_node_id(path),
                        path=path,
                        line=binding.line,
                        kind="import",
                        expression=(
                            f"{binding.module_name}"
                            + (
                                f".{binding.imported_name}"
                                if binding.imported_name
                                else ""
                            )
                        ),
                        reason=(
                            "Import target is not uniquely resolvable within "
                            "the supplied repository source snapshot."
                        ),
                    )
                )
                continue

            graph.add_edge(
                GraphEdge(
                    source=_file_node_id(path),
                    target=_file_node_id(target_path),
                    kind="imports",
                    source_path=path,
                    line=binding.line,
                    evidence=(
                        f"import {binding.module_name}"
                        + (
                            f" / {binding.imported_name}"
                            if binding.imported_name
                            else ""
                        )
                    ),
                )
            )

            # If a named symbol is imported, link it only when exactly one
            # definition of that name exists in the imported file.
            if binding.imported_name:
                matching = [
                    node
                    for node in graph.nodes.values()
                    if node.path == target_path
                    and node.name == binding.imported_name
                    and node.kind in {"function", "method", "class"}
                ]

                if len(matching) == 1:
                    graph.add_edge(
                        GraphEdge(
                            source=_file_node_id(path),
                            target=matching[0].id,
                            kind="imports_symbol",
                            source_path=path,
                            line=binding.line,
                            evidence=(
                                f"from {resolved_module} import "
                                f"{binding.imported_name}"
                            ),
                        )
                    )

    def _resolve_references(
        self,
        analyzers: Mapping[str, _PythonFileAnalyzer],
        graph: DependencyGraph,
    ) -> None:
        """
        Resolve local and explicitly imported symbols.

        This intentionally does not infer runtime types or guess which class
        an arbitrary variable refers to.
        """
        definitions_by_path_and_name: dict[
            tuple[str, str], list[_Definition]
        ] = defaultdict(list)

        definitions_by_name: dict[str, list[_Definition]] = defaultdict(list)

        for analyzer in analyzers.values():
            for definition in analyzer.definitions:
                definitions_by_path_and_name[
                    (definition.path, definition.name)
                ].append(definition)
                definitions_by_name[definition.name].append(definition)

        imports_by_path: dict[str, dict[str, str]] = defaultdict(dict)

        for path, analyzer in analyzers.items():
            for binding in analyzer.imports:
                module_name = binding.module_name.lstrip(".")
                target_module_path = self._build_module_index(
                    analyzers.keys()
                ).get(module_name)

                if not target_module_path and binding.imported_name:
                    target_module_path = self._build_module_index(
                        analyzers.keys()
                    ).get(f"{module_name}.{binding.imported_name}")

                if target_module_path:
                    imports_by_path[path][binding.local_name] = target_module_path

        for path, analyzer in analyzers.items():
            for reference in analyzer.references:
                expression_parts = reference.expression.split(".")
                first_name = expression_parts[0]
                resolved: Optional[_Definition] = None
                resolution_kind = "calls"

                # Calls to a local function or method can be linked when the
                # name has exactly one candidate in the current file.
                local_candidates = definitions_by_path_and_name.get(
                    (path, first_name),
                    [],
                )

                if reference.kind == "call" and len(local_candidates) == 1:
                    resolved = local_candidates[0]

                # Calls through an imported module: module.function().
                elif reference.kind == "call" and first_name in imports_by_path[path]:
                    imported_path = imports_by_path[path][first_name]
                    if len(expression_parts) >= 2:
                        symbol_name = expression_parts[-1]
                        candidates = definitions_by_path_and_name.get(
                            (imported_path, symbol_name),
                            [],
                        )
                        if len(candidates) == 1:
                            resolved = candidates[0]

                # Direct imported symbol call: imported_function().
                elif reference.kind == "call":
                    imported_binding = next(
                        (
                            binding
                            for binding in analyzer.imports
                            if binding.local_name == first_name
                            and binding.imported_name
                        ),
                        None,
                    )

                    if imported_binding:
                        module_name = imported_binding.module_name.lstrip(".")
                        module_index = self._build_module_index(
                            analyzers.keys()
                        )
                        target_path = module_index.get(module_name)

                        if target_path is None:
                            target_path = module_index.get(
                                f"{module_name}.{imported_binding.imported_name}"
                            )

                        if target_path:
                            candidates = definitions_by_path_and_name.get(
                                (target_path, imported_binding.imported_name),
                                [],
                            )
                            if len(candidates) == 1:
                                resolved = candidates[0]

                if resolved is not None:
                    graph.add_edge(
                        GraphEdge(
                            source=reference.source_node_id,
                            target=resolved.node_id,
                            kind=resolution_kind,
                            source_path=path,
                            line=reference.line,
                            evidence=reference.expression,
                        )
                    )
                    continue

                if reference.kind == "call":
                    # Builtins and common language primitives do not represent
                    # repository-local dependencies.
                    if first_name in dir(__builtins__):
                        continue

                    graph.add_unresolved(
                        UnresolvedReference(
                            source=reference.source_node_id,
                            path=path,
                            line=reference.line,
                            kind="call",
                            expression=reference.expression,
                            reason=(
                                "No unique repository-local call target "
                                "could be established statically."
                            ),
                        )
                    )

                elif reference.kind == "attribute_reference":
                    # Record a source-level attribute node without claiming
                    # that the receiver is a specific model or object type.
                    attribute_name = expression_parts[-1]

                    attribute_id = _attribute_node_id(
                        path,
                        reference.source_node_id,
                        attribute_name,
                    )

                    graph.add_node(
                        GraphNode(
                            id=attribute_id,
                            kind="attribute_reference",
                            path=path,
                            name=attribute_name,
                            line=reference.line,
                            metadata={
                                "expression": reference.expression,
                                "owner_node_id": reference.source_node_id,
                                "receiver_type": "unknown",
                            },
                        )
                    )

                    graph.add_edge(
                        GraphEdge(
                            source=reference.source_node_id,
                            target=attribute_id,
                            kind="references_attribute",
                            source_path=path,
                            line=reference.line,
                            evidence=reference.expression,
                        )
                    )

    @staticmethod
    def _analyze_template(
        *,
        path: str,
        source: str,
        graph: DependencyGraph,
    ) -> None:
        """
        Record syntactic Jinja-style attribute references.

        A template reference is not linked to a Python model unless another
        verified relationship explicitly establishes that connection.
        """
        file_id = _file_node_id(path)

        # Examples: appointment.date, patient.name, item.doctor.full_name
        pattern = re.compile(
            r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\b"
        )

        for line_number, line_text in enumerate(source.splitlines(), start=1):
            for match in pattern.finditer(line_text):
                expression = match.group(1)
                attribute_name = expression.rsplit(".", 1)[-1]

                attribute_id = _attribute_node_id(
                    path,
                    "template",
                    f"line_{line_number}.{attribute_name}",
                )

                graph.add_node(
                    GraphNode(
                        id=attribute_id,
                        kind="template_attribute_reference",
                        path=path,
                        name=attribute_name,
                        line=line_number,
                        metadata={
                            "expression": expression,
                            "receiver_type": "unknown",
                        },
                    )
                )

                graph.add_edge(
                    GraphEdge(
                        source=file_id,
                        target=attribute_id,
                        kind="references_attribute",
                        source_path=path,
                        line=line_number,
                        evidence=expression,
                    )
                )


# ---------------------------------------------------------------------------
# Public convenience function
# ---------------------------------------------------------------------------

def build_dependency_graph(
    source_files: Mapping[str, str],
    *,
    max_files: int = DEFAULT_MAX_FILES,
    max_nodes: int = DEFAULT_MAX_NODES,
    max_edges: int = DEFAULT_MAX_EDGES,
) -> DependencyGraph:
    """
    Convenience wrapper for callers that do not need a persistent builder.
    """
    return DependencyGraphBuilder(
        max_files=max_files,
        max_nodes=max_nodes,
        max_edges=max_edges,
    ).build(source_files)
