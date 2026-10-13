
"""
app/modules/search/pipeline/dependency_graph.py

Deterministic, read-only dependency graph builder for RepoLens Deep Search.

Responsibilities:
    - Discover Python files, imports, classes, functions, methods and calls.
    - Resolve absolute/relative imports and imported aliases when unambiguous.
    - Record Python attribute references with their containing scope.
    - Discover template references and common render_template context mappings.
    - Link template references to verified context variables and render callers.
    - Preserve unresolved references rather than guessing relationships.
    - Apply bounded node/edge/file construction with truncation metadata.

This module does not access the filesystem, create a Qdrant client, call an
LLM, write repository files, or infer a model type from a matching name.
The caller supplies a read-only mapping of relative file paths to source text.
"""

from __future__ import annotations

import ast
import logging
import posixpath
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional

logger = logging.getLogger(__name__)

DEFAULT_MAX_FILES = 500
DEFAULT_MAX_NODES = 10_000
DEFAULT_MAX_EDGES = 25_000
DEFAULT_MAX_DEPTH = 3

PYTHON_EXTENSIONS = {".py"}
TEMPLATE_EXTENSIONS = {".html", ".htm", ".jinja", ".j2", ".jinja2"}
TYPESCRIPT_EXTENSIONS = {".ts", ".tsx"}
JAVASCRIPT_EXTENSIONS = {".js", ".jsx", ".mjs", ".cjs"}
SOURCE_EXTENSIONS = (
    PYTHON_EXTENSIONS
    | TEMPLATE_EXTENSIONS
    | TYPESCRIPT_EXTENSIONS
    | JAVASCRIPT_EXTENSIONS
)

_TS_PARSER = None
_TSX_PARSER = None


def _get_ts_parser(tsx: bool = False):
    """Lazily load and cache tree-sitter parser for TypeScript/JavaScript."""
    global _TS_PARSER, _TSX_PARSER
    try:
        import tree_sitter
        import tree_sitter_typescript

        if tsx:
            if _TSX_PARSER is None:
                lang = tree_sitter.Language(
                    tree_sitter_typescript.language_tsx()
                )
                _TSX_PARSER = tree_sitter.Parser(lang)
            return _TSX_PARSER
        else:
            if _TS_PARSER is None:
                lang = tree_sitter.Language(
                    tree_sitter_typescript.language_typescript()
                )
                _TS_PARSER = tree_sitter.Parser(lang)
            return _TS_PARSER
    except Exception as exc:
        logger.warning(
            "Tree-sitter parser initialization failed: %s", exc
        )
        return None


def _resolve_ts_import_path(
    current_path: str,
    import_module: str,
    available_paths: Iterable[str],
) -> Optional[str]:
    """Resolve a TypeScript/JavaScript import path against available repo paths."""
    if not import_module:
        return None

    mod = import_module.strip("'\"`")
    if mod.startswith("./") or mod.startswith("../"):
        base_dir = posixpath.dirname(current_path)
        combined = posixpath.normpath(posixpath.join(base_dir, mod))
    elif mod.startswith("/"):
        combined = posixpath.normpath(mod.lstrip("/"))
    else:
        if mod.startswith("@/"):
            combined = posixpath.normpath(re.sub(r"^@/", "src/", mod))
        else:
            combined = posixpath.normpath(mod)

    path_set = set(available_paths)
    candidates = [
        combined,
        combined + ".ts",
        combined + ".tsx",
        combined + ".d.ts",
        combined + ".js",
        combined + ".jsx",
        combined + ".mjs",
        combined + ".cjs",
        combined + "/index.ts",
        combined + "/index.tsx",
        combined + "/index.js",
        combined + "/index.jsx",
    ]

    for cand in candidates:
        if cand in path_set:
            return cand

    for ext in (".ts", ".tsx", ".js", ".jsx"):
        target_suffix = combined + ext
        for path in path_set:
            if path.endswith(target_suffix) or path.endswith("/" + target_suffix):
                return path

    return None

IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
}

TEMPLATE_REFERENCE_RE = re.compile(
    r"""
    \b
    (?P<root>[A-Za-z_]\w*)
    (?P<tail>(?:\s*(?:\.\s*[A-Za-z_]\w*|\[\s*["'][^"']+["']\s*\]))+)
    """,
    re.VERBOSE,
)

TEMPLATE_CALL_RE = re.compile(
    r"""
    \b(?:render_template|render_template_string)\s*
    \(\s*
    (?P<quote>['"])
    (?P<template>[^'"]+)
    (?P=quote)
    """,
    re.VERBOSE,
)

PYTHON_TEMPLATE_CALL_NAMES = {
    "render_template",
    "render_template_string",
}


@dataclass
class GraphNode:
    """One file, symbol, call, or source reference in the graph."""

    id: str
    kind: str
    name: str
    path: str
    line: Optional[int] = None
    end_line: Optional[int] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEdge:
    """A directed, evidence-backed graph relationship."""

    source: str
    target: str
    kind: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def evidence(self) -> str:
        return str(
            self.metadata.get("evidence")
            or self.metadata.get("expression")
            or ""
        )


@dataclass
class UnresolvedReference:
    """A relationship that could not be resolved without guessing."""

    source: str
    name: str
    kind: str
    path: str
    line: Optional[int] = None
    reason: str = "unresolved"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def expression(self) -> str:
        return self.name


@dataclass
class DependencyGraph:
    """Graph storage and bounded traversal helpers."""

    nodes: dict[str, GraphNode] = field(default_factory=dict)
    edges: list[GraphEdge] = field(default_factory=list)
    unresolved_references: list[UnresolvedReference] = field(
        default_factory=list
    )
    metadata: dict[str, Any] = field(default_factory=dict)

    _edge_keys: set[tuple[str, str, str]] = field(
        default_factory=set,
        repr=False,
    )
    _outgoing: dict[str, list[GraphEdge]] = field(
        default_factory=lambda: defaultdict(list),
        repr=False,
    )
    _incoming: dict[str, list[GraphEdge]] = field(
        default_factory=lambda: defaultdict(list),
        repr=False,
    )

    @property
    def unresolved(self) -> list[UnresolvedReference]:
        """Compatibility alias for consumers using graph.unresolved."""
        return self.unresolved_references

    def add_node(self, node: GraphNode) -> bool:
        if node.id in self.nodes:
            return True

        max_nodes = self.metadata.get("max_nodes", DEFAULT_MAX_NODES)
        if len(self.nodes) >= max_nodes:
            self.metadata["node_limit_reached"] = True
            self.metadata["nodes_skipped_by_limit"] = (
                self.metadata.get("nodes_skipped_by_limit", 0) + 1
            )
            return False

        self.nodes[node.id] = node
        return True

    def add_edge(self, edge: GraphEdge) -> bool:
        if edge.source not in self.nodes or edge.target not in self.nodes:
            self.metadata["edges_skipped_missing_endpoint"] = (
                self.metadata.get("edges_skipped_missing_endpoint", 0) + 1
            )
            return False

        key = (edge.source, edge.target, edge.kind)
        if key in self._edge_keys:
            return True

        max_edges = self.metadata.get("max_edges", DEFAULT_MAX_EDGES)
        if len(self.edges) >= max_edges:
            self.metadata["edge_limit_reached"] = True
            self.metadata["edges_skipped_by_limit"] = (
                self.metadata.get("edges_skipped_by_limit", 0) + 1
            )
            return False

        self._edge_keys.add(key)
        self.edges.append(edge)
        self._outgoing[edge.source].append(edge)
        self._incoming[edge.target].append(edge)
        return True

    def add_unresolved(self, reference: UnresolvedReference) -> None:
        self.unresolved_references.append(reference)

    def outgoing(
        self,
        node_id: str,
        kinds: Optional[Iterable[str]] = None,
    ) -> list[GraphEdge]:
        edges = list(self._outgoing.get(node_id, []))
        if kinds is not None:
            kind_set = set(kinds)
            return [e for e in edges if e.kind in kind_set]
        return edges

    def incoming(
        self,
        node_id: str,
        kinds: Optional[Iterable[str]] = None,
    ) -> list[GraphEdge]:
        edges = list(self._incoming.get(node_id, []))
        if kinds is not None:
            kind_set = set(kinds)
            return [e for e in edges if e.kind in kind_set]
        return edges

    def traverse(
        self,
        start_ids: Iterable[str],
        max_depth: int = DEFAULT_MAX_DEPTH,
        bidirectional: bool = True,
    ) -> list[GraphNode]:
        """Return nodes reachable within max_depth, without repeating nodes."""
        depth_limit = max(0, int(max_depth))
        queue: deque[tuple[str, int]] = deque()
        visited: set[str] = set()
        result: list[GraphNode] = []

        for start_id in start_ids:
            if start_id in self.nodes and start_id not in visited:
                visited.add(start_id)
                queue.append((start_id, 0))
                result.append(self.nodes[start_id])

        while queue:
            current_id, depth = queue.popleft()
            if depth >= depth_limit:
                continue

            edges = list(self._outgoing.get(current_id, []))
            if bidirectional:
                edges.extend(self._incoming.get(current_id, []))

            for edge in edges:
                neighbor = (
                    edge.target
                    if edge.source == current_id
                    else edge.source
                )

                if neighbor in visited or neighbor not in self.nodes:
                    continue

                visited.add(neighbor)
                queue.append((neighbor, depth + 1))
                result.append(self.nodes[neighbor])

        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [
                {
                    "id": node.id,
                    "kind": node.kind,
                    "name": node.name,
                    "path": node.path,
                    "line": node.line,
                    "end_line": node.end_line,
                    "metadata": dict(node.metadata),
                }
                for node in self.nodes.values()
            ],
            "edges": [
                {
                    "source": edge.source,
                    "target": edge.target,
                    "kind": edge.kind,
                    "metadata": dict(edge.metadata),
                }
                for edge in self.edges
            ],
            "unresolved_references": [
                {
                    "source": ref.source,
                    "name": ref.name,
                    "kind": ref.kind,
                    "path": ref.path,
                    "line": ref.line,
                    "reason": ref.reason,
                    "metadata": dict(ref.metadata),
                }
                for ref in self.unresolved_references
            ],
            "metadata": dict(self.metadata),
        }


def _normalize_path(path: str) -> str:
    """Normalize a relative repository path without accessing the filesystem."""
    normalized = path.replace("\\", "/").strip()
    normalized = posixpath.normpath(normalized)

    while normalized.startswith("./"):
        normalized = normalized[2:]

    return normalized


def _is_ignored_path(path: str) -> bool:
    return any(part in IGNORED_DIRS for part in path.split("/"))


def _extension(path: str) -> str:
    return posixpath.splitext(path)[1].lower()


def _module_name(path: str) -> Optional[str]:
    """Convert a Python path to a best-effort importable module name."""
    if not path.endswith(".py"):
        return None

    module_path = path[:-3]
    if module_path == "__init__":
        return ""

    if module_path.endswith("/__init__"):
        module_path = module_path[: -len("/__init__")]

    module = module_path.replace("/", ".").strip(".")
    if not module:
        return None

    parts = module.split(".")
    if not all(part.isidentifier() for part in parts):
        return None

    return module


def _package_name(path: str) -> str:
    """Return the containing Python package for relative import resolution."""
    module = _module_name(path)
    if module is None:
        return ""

    if path.endswith("/__init__.py") or path == "__init__.py":
        return module

    if "." not in module:
        return ""

    return module.rsplit(".", 1)[0]


def _node_id(kind: str, path: str, line: Optional[int], name: str) -> str:
    safe_name = name.replace("\\", "/")
    return f"{kind}:{path}:{line if line is not None else 0}:{safe_name}"


def _attribute_expression(node: ast.AST) -> Optional[str]:
    """Render a simple dotted attribute expression without evaluating it."""
    parts: list[str] = []
    current = node

    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value

    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))

    return None


def _call_expression(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id

    if isinstance(node, ast.Attribute):
        return _attribute_expression(node)

    return None


def _template_attribute_expression(match: re.Match[str]) -> str:
    root = match.group("root")
    tail = match.group("tail")
    parts = re.findall(r"\.\s*([A-Za-z_]\w*)", tail)
    return ".".join([root, *parts])


@dataclass
class _ImportBinding:
    local_name: str
    module_name: str
    symbol_name: Optional[str]
    line: int
    import_node_id: str


@dataclass
class _Definition:
    name: str
    qualified_name: str
    kind: str
    path: str
    line: int
    end_line: int
    node_id: str
    parent_class: Optional[str] = None


@dataclass
class _CallReference:
    expression: str
    path: str
    line: int
    containing_symbol_id: str
    containing_qualname: str
    node_id: str


@dataclass
class _AttributeReference:
    expression: str
    path: str
    line: int
    containing_symbol_id: str
    node_id: str


@dataclass
class _TemplateReference:
    expression: str
    root: str
    path: str
    line: int
    node_id: str


@dataclass
class _TemplateRender:
    template_name: str
    path: str
    line: int
    containing_symbol_id: str
    context_bindings: dict[str, str]
    node_id: str


class _PythonFileAnalyzer(ast.NodeVisitor):
    """Collect syntax-level evidence from one Python file."""

    def __init__(
        self,
        path: str,
        graph: DependencyGraph,
        file_node_id: str,
    ) -> None:
        self.path = path
        self.graph = graph
        self.file_node_id = file_node_id

        self.definitions: list[_Definition] = []
        self.import_bindings: list[_ImportBinding] = []
        self.calls: list[_CallReference] = []
        self.attributes: list[_AttributeReference] = []
        self.template_renders: list[_TemplateRender] = []

        self._scope: list[tuple[str, str, Optional[str]]] = []
        self._class_stack: list[str] = []

    def _current_symbol_id(self) -> str:
        return self._scope[-1][1] if self._scope else self.file_node_id

    def _current_qualname(self) -> str:
        return self._scope[-1][0] if self._scope else "<module>"

    def _add_symbol(
        self,
        node: ast.AST,
        name: str,
        kind: str,
        parent_qualname: Optional[str] = None,
    ) -> _Definition:
        line = getattr(node, "lineno", 1)
        end_line = getattr(node, "end_lineno", line)

        if parent_qualname:
            qualified_name = f"{parent_qualname}.{name}"
        else:
            qualified_name = name

        parent_class = self._class_stack[-1] if self._class_stack else None

        symbol_node_id = _node_id(kind, self.path, line, qualified_name)
        graph_node = GraphNode(
            id=symbol_node_id,
            kind=kind,
            name=name,
            path=self.path,
            line=line,
            end_line=end_line,
            metadata={
                "qualified_name": qualified_name,
                "parent_class": parent_class,
            },
        )

        if self.graph.add_node(graph_node):
            self.graph.add_edge(
                GraphEdge(
                    source=self.file_node_id,
                    target=symbol_node_id,
                    kind="defines",
                    metadata={"line": line},
                )
            )

        definition = _Definition(
            name=name,
            qualified_name=qualified_name,
            kind=kind,
            path=self.path,
            line=line,
            end_line=end_line,
            node_id=symbol_node_id,
            parent_class=parent_class,
        )
        self.definitions.append(definition)
        return definition

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local_name = alias.asname or alias.name.split(".")[0]
            import_id = _node_id(
                "import",
                self.path,
                node.lineno,
                f"{local_name}={alias.name}",
            )
            if self.graph.add_node(
                GraphNode(
                    id=import_id,
                    kind="import",
                    name=alias.name,
                    path=self.path,
                    line=node.lineno,
                    metadata={
                        "local_name": local_name,
                        "module_name": alias.name,
                        "symbol_name": None,
                        "alias": alias.asname,
                    },
                )
            ):
                self.graph.add_edge(
                    GraphEdge(
                        source=self.file_node_id,
                        target=import_id,
                        kind="imports",
                        metadata={"line": node.lineno},
                    )
                )

            self.import_bindings.append(
                _ImportBinding(
                    local_name=local_name,
                    module_name=alias.name,
                    symbol_name=None,
                    line=node.lineno,
                    import_node_id=import_id,
                )
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module_name = node.module or ""

        # Store the relative level. The resolver computes the absolute module
        # using the current file's package context.
        for alias in node.names:
            if alias.name == "*":
                self.graph.add_unresolved(
                    UnresolvedReference(
                        source=self.file_node_id,
                        name=f"from {'.' * node.level}{module_name} import *",
                        kind="wildcard_import",
                        path=self.path,
                        line=node.lineno,
                        reason="wildcard_import_not_expanded",
                    )
                )
                continue

            local_name = alias.asname or alias.name
            import_id = _node_id(
                "import",
                self.path,
                node.lineno,
                f"{'.' * node.level}{module_name}.{alias.name}",
            )

            if self.graph.add_node(
                GraphNode(
                    id=import_id,
                    kind="import",
                    name=alias.name,
                    path=self.path,
                    line=node.lineno,
                    metadata={
                        "local_name": local_name,
                        "module_name": module_name,
                        "symbol_name": alias.name,
                        "relative_level": node.level,
                        "alias": alias.asname,
                    },
                )
            ):
                self.graph.add_edge(
                    GraphEdge(
                        source=self.file_node_id,
                        target=import_id,
                        kind="imports",
                        metadata={"line": node.lineno},
                    )
                )

            self.import_bindings.append(
                _ImportBinding(
                    local_name=local_name,
                    module_name=("." * node.level) + module_name,
                    symbol_name=alias.name,
                    line=node.lineno,
                    import_node_id=import_id,
                )
            )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        parent = self._current_qualname()
        parent_name = None if parent == "<module>" else parent
        definition = self._add_symbol(node, node.name, "class", parent_name)

        # Record declared base expressions as evidence, but do not assume
        # that an unresolved base is a local class.
        for base in node.bases:
            base_name = _call_expression(base) or ast.dump(
                base,
                include_attributes=False,
            )
            self.graph.add_unresolved(
                UnresolvedReference(
                    source=definition.node_id,
                    name=base_name,
                    kind="class_base",
                    path=self.path,
                    line=getattr(base, "lineno", node.lineno),
                    reason="base_class_resolution_not_guaranteed",
                )
            )

        self._class_stack.append(definition.qualified_name)
        self._scope.append(
            (definition.qualified_name, definition.node_id, "class")
        )

        for child in node.body:
            self.visit(child)

        self._scope.pop()
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        parent = self._current_qualname()
        parent_name = None if parent == "<module>" else parent
        kind = "method" if self._class_stack else "function"
        definition = self._add_symbol(node, node.name, kind, parent_name)

        self._scope.append(
            (definition.qualified_name, definition.node_id, kind)
        )
        for child in node.body:
            self.visit(child)
        self._scope.pop()

    def visit_Call(self, node: ast.Call) -> None:
        expression = _call_expression(node.func)

        if expression:
            line = getattr(node, "lineno", 1)
            call_id = _node_id("call", self.path, line, expression)

            if self.graph.add_node(
                GraphNode(
                    id=call_id,
                    kind="call",
                    name=expression,
                    path=self.path,
                    line=line,
                    metadata={
                        "expression": expression,
                        "containing_qualname": self._current_qualname(),
                    },
                )
            ):
                self.graph.add_edge(
                    GraphEdge(
                        source=self._current_symbol_id(),
                        target=call_id,
                        kind="contains_call",
                        metadata={"line": line},
                    )
                )

            self.calls.append(
                _CallReference(
                    expression=expression,
                    path=self.path,
                    line=line,
                    containing_symbol_id=self._current_symbol_id(),
                    containing_qualname=self._current_qualname(),
                    node_id=call_id,
                )
            )

            leaf_name = expression.rsplit(".", 1)[-1]
            if leaf_name in PYTHON_TEMPLATE_CALL_NAMES:
                self._record_template_render(node, call_id)

        self.generic_visit(node)

    def _record_template_render(
        self,
        node: ast.Call,
        call_id: str,
    ) -> None:
        if not node.args or not isinstance(node.args[0], ast.Constant):
            return

        template_value = node.args[0].value
        if not isinstance(template_value, str):
            return

        bindings: dict[str, str] = {}

        for keyword in node.keywords:
            if keyword.arg is None:
                # **kwargs cannot be safely expanded statically.
                continue

            value_expression = (
                _call_expression(keyword.value)
                or _attribute_expression(keyword.value)
            )

            if value_expression is None and isinstance(
                keyword.value, ast.Constant
            ):
                value_expression = repr(keyword.value.value)

            if value_expression is not None:
                bindings[keyword.arg] = value_expression

        self.template_renders.append(
            _TemplateRender(
                template_name=template_value,
                path=self.path,
                line=getattr(node, "lineno", 1),
                containing_symbol_id=self._current_symbol_id(),
                context_bindings=bindings,
                node_id=call_id,
            )
        )

    def visit_Attribute(self, node: ast.Attribute) -> None:
        expression = _attribute_expression(node)
        if expression:
            line = getattr(node, "lineno", 1)
            attribute_id = _node_id(
                "attribute",
                self.path,
                line,
                expression,
            )

            if self.graph.add_node(
                GraphNode(
                    id=attribute_id,
                    kind="attribute_reference",
                    name=expression,
                    path=self.path,
                    line=line,
                    metadata={
                        "expression": expression,
                        "root": expression.split(".", 1)[0],
                        "containing_qualname": self._current_qualname(),
                    },
                )
            ):
                self.graph.add_edge(
                    GraphEdge(
                        source=self._current_symbol_id(),
                        target=attribute_id,
                        kind="references_attribute",
                        metadata={"line": line},
                    )
                )

            self.attributes.append(
                _AttributeReference(
                    expression=expression,
                    path=self.path,
                    line=line,
                    containing_symbol_id=self._current_symbol_id(),
                    node_id=attribute_id,
                )
            )

        self.generic_visit(node)


class _TreeSitterFileAnalyzer:
    """Collect syntax-level evidence from TypeScript and JavaScript files."""

    def __init__(
        self,
        path: str,
        graph: DependencyGraph,
        file_node_id: str,
    ) -> None:
        self.path = path
        self.graph = graph
        self.file_node_id = file_node_id

        self.definitions: list[_Definition] = []
        self.import_bindings: list[_ImportBinding] = []
        self.calls: list[_CallReference] = []
        self.attributes: list[_AttributeReference] = []
        self.template_renders: list[_TemplateRender] = []

        self._scope: list[tuple[str, str, Optional[str]]] = []
        self._class_stack: list[str] = []

    def _current_symbol_id(self) -> str:
        return self._scope[-1][1] if self._scope else self.file_node_id

    def _current_qualname(self) -> str:
        return self._scope[-1][0] if self._scope else "<module>"

    def _add_symbol(
        self,
        name: str,
        kind: str,
        line: int,
        end_line: int,
        parent_qualname: Optional[str] = None,
    ) -> _Definition:
        if parent_qualname:
            qualified_name = f"{parent_qualname}.{name}"
        else:
            qualified_name = name

        parent_class = self._class_stack[-1] if self._class_stack else None

        symbol_node_id = _node_id(kind, self.path, line, qualified_name)
        graph_node = GraphNode(
            id=symbol_node_id,
            kind=kind,
            name=name,
            path=self.path,
            line=line,
            end_line=end_line,
            metadata={
                "qualified_name": qualified_name,
                "parent_class": parent_class,
            },
        )

        if self.graph.add_node(graph_node):
            self.graph.add_edge(
                GraphEdge(
                    source=self.file_node_id,
                    target=symbol_node_id,
                    kind="defines",
                    metadata={"line": line},
                )
            )

        definition = _Definition(
            name=name,
            qualified_name=qualified_name,
            kind=kind,
            path=self.path,
            line=line,
            end_line=end_line,
            node_id=symbol_node_id,
            parent_class=parent_class,
        )
        self.definitions.append(definition)
        return definition

    def analyze(self, root_node: Any, source_bytes: bytes) -> None:
        def get_text(node: Any) -> str:
            return source_bytes[node.start_byte : node.end_byte].decode(
                "utf8", errors="ignore"
            )

        def visit(node: Any) -> None:
            ntype = node.type

            # Imports: import { A, B as C } from './dto'
            if ntype == "import_statement":
                self._visit_import_statement(node, get_text)
                return

            # Class declaration
            if ntype == "class_declaration":
                self._visit_class(node, get_text, visit)
                return

            # Interface declaration
            if ntype == "interface_declaration":
                self._visit_interface(node, get_text, visit)
                return

            # Function declaration
            if ntype == "function_declaration":
                self._visit_function(node, get_text, visit)
                return

            # Method definition inside a class/object
            if ntype == "method_definition":
                self._visit_method(node, get_text, visit)
                return

            # Property definitions
            if ntype in (
                "public_field_definition",
                "field_definition",
                "property_signature",
            ):
                self._visit_field(node, get_text)
                return

            # Variable declaration (e.g. const helper = () => { ... } or const x = require('./x'))
            if ntype in ("lexical_declaration", "variable_declaration"):
                self._visit_variable_declaration(node, get_text, visit)
                return

            # Call expression: foo(), this.bar(), obj.method()
            if ntype == "call_expression":
                self._visit_call(node, get_text, visit)
                return

            # Member expression: this.mimojoCardId, obj.prop
            if ntype == "member_expression":
                self._visit_member(node, get_text, visit)
                return

            # Export statement: export class Foo ...
            if ntype == "export_statement":
                for child in node.children:
                    if child.type not in ("export", "default"):
                        visit(child)
                return

            for child in node.children:
                visit(child)

        visit(root_node)

    def _visit_import_statement(self, node: Any, get_text: Any) -> None:
        source_module = ""
        bindings: list[tuple[str, Optional[str]]] = []
        line = node.start_point.row + 1

        for child in node.children:
            if child.type == "string":
                source_module = get_text(child).strip("'\"`")
            elif child.type == "import_clause":
                for clause_child in child.children:
                    if clause_child.type == "identifier":
                        name = get_text(clause_child)
                        bindings.append((name, None))
                    elif clause_child.type == "namespace_import":
                        for ns_child in clause_child.children:
                            if ns_child.type == "identifier":
                                bindings.append((get_text(ns_child), None))
                                break
                    elif clause_child.type == "named_imports":
                        for spec in clause_child.children:
                            if spec.type == "import_specifier":
                                idents = [
                                    c
                                    for c in spec.children
                                    if c.type == "identifier"
                                ]
                                if len(idents) == 1:
                                    name = get_text(idents[0])
                                    bindings.append((name, name))
                                elif len(idents) >= 2:
                                    orig_name = get_text(idents[0])
                                    alias_name = get_text(idents[1])
                                    bindings.append((alias_name, orig_name))

        if not source_module:
            return

        for local_name, symbol_name in bindings:
            import_id = _node_id(
                "import",
                self.path,
                line,
                f"{local_name}={source_module}.{symbol_name or ''}",
            )
            if self.graph.add_node(
                GraphNode(
                    id=import_id,
                    kind="import",
                    name=symbol_name or local_name,
                    path=self.path,
                    line=line,
                    metadata={
                        "local_name": local_name,
                        "module_name": source_module,
                        "symbol_name": symbol_name,
                        "alias": (
                            local_name if local_name != symbol_name else None
                        ),
                    },
                )
            ):
                self.graph.add_edge(
                    GraphEdge(
                        source=self.file_node_id,
                        target=import_id,
                        kind="imports",
                        metadata={"line": line},
                    )
                )

            self.import_bindings.append(
                _ImportBinding(
                    local_name=local_name,
                    module_name=source_module,
                    symbol_name=symbol_name,
                    line=line,
                    import_node_id=import_id,
                )
            )

    def _visit_class(self, node: Any, get_text: Any, visit: Any) -> None:
        name = None
        line = node.start_point.row + 1
        end_line = node.end_point.row + 1

        for child in node.children:
            if child.type in ("type_identifier", "identifier"):
                name = get_text(child)
                break

        if not name:
            for child in node.children:
                visit(child)
            return

        parent = self._current_qualname()
        parent_name = None if parent == "<module>" else parent
        definition = self._add_symbol(
            name, "class", line, end_line, parent_name
        )

        for child in node.children:
            if child.type == "class_heritage":
                base_expr = get_text(child).replace("extends", "").strip()
                if base_expr:
                    self.graph.add_unresolved(
                        UnresolvedReference(
                            source=definition.node_id,
                            name=base_expr,
                            kind="class_base",
                            path=self.path,
                            line=line,
                            reason="base_class_resolution_not_guaranteed",
                        )
                    )

        self._class_stack.append(definition.qualified_name)
        self._scope.append(
            (definition.qualified_name, definition.node_id, "class")
        )

        for child in node.children:
            if child.type == "class_body":
                for member in child.children:
                    visit(member)

        self._scope.pop()
        self._class_stack.pop()

    def _visit_interface(self, node: Any, get_text: Any, visit: Any) -> None:
        name = None
        line = node.start_point.row + 1
        end_line = node.end_point.row + 1

        for child in node.children:
            if child.type in ("type_identifier", "identifier"):
                name = get_text(child)
                break

        if not name:
            return

        parent = self._current_qualname()
        parent_name = None if parent == "<module>" else parent
        definition = self._add_symbol(
            name, "interface", line, end_line, parent_name
        )

        self._class_stack.append(definition.qualified_name)
        self._scope.append(
            (definition.qualified_name, definition.node_id, "interface")
        )

        for child in node.children:
            if child.type == "interface_body":
                for member in child.children:
                    visit(member)

        self._scope.pop()
        self._class_stack.pop()

    def _visit_function(self, node: Any, get_text: Any, visit: Any) -> None:
        name = None
        line = node.start_point.row + 1
        end_line = node.end_point.row + 1

        for child in node.children:
            if child.type == "identifier":
                name = get_text(child)
                break

        if not name:
            for child in node.children:
                visit(child)
            return

        parent = self._current_qualname()
        parent_name = None if parent == "<module>" else parent
        kind = "method" if self._class_stack else "function"
        definition = self._add_symbol(name, kind, line, end_line, parent_name)

        self._scope.append(
            (definition.qualified_name, definition.node_id, kind)
        )
        for child in node.children:
            if child.type == "statement_block":
                for stmt in child.children:
                    visit(stmt)
        self._scope.pop()

    def _visit_method(self, node: Any, get_text: Any, visit: Any) -> None:
        name = None
        line = node.start_point.row + 1
        end_line = node.end_point.row + 1

        for child in node.children:
            if child.type in ("property_identifier", "identifier"):
                name = get_text(child)
                break

        if not name:
            for child in node.children:
                visit(child)
            return

        parent = self._current_qualname()
        parent_name = None if parent == "<module>" else parent
        definition = self._add_symbol(
            name, "method", line, end_line, parent_name
        )

        self._scope.append(
            (definition.qualified_name, definition.node_id, "method")
        )
        for child in node.children:
            if child.type == "statement_block":
                for stmt in child.children:
                    visit(stmt)
        self._scope.pop()

    def _visit_field(self, node: Any, get_text: Any) -> None:
        name = None
        line = node.start_point.row + 1
        end_line = node.end_point.row + 1

        for child in node.children:
            if child.type in ("property_identifier", "identifier"):
                name = get_text(child)
                break

        if not name:
            return

        parent = self._current_qualname()
        parent_name = None if parent == "<module>" else parent
        self._add_symbol(name, "property", line, end_line, parent_name)

    def _visit_variable_declaration(
        self, node: Any, get_text: Any, visit: Any
    ) -> None:
        for declarator in node.children:
            if declarator.type == "variable_declarator":
                id_node = declarator.child_by_field_name("name")
                value_node = declarator.child_by_field_name("value")

                if value_node and value_node.type == "call_expression":
                    fn = value_node.child_by_field_name("function")
                    args = value_node.child_by_field_name("arguments")
                    if fn and get_text(fn) == "require" and args:
                        source_mod = ""
                        for arg_child in args.children:
                            if arg_child.type == "string":
                                source_mod = get_text(arg_child).strip(
                                    "'\"`"
                                )
                        if source_mod and id_node:
                            line = declarator.start_point.row + 1
                            if id_node.type == "identifier":
                                local_name = get_text(id_node)
                                self._record_require_import(
                                    local_name, None, source_mod, line
                                )
                            elif id_node.type == "object_pattern":
                                for prop in id_node.children:
                                    if prop.type in (
                                        "shorthand_property_identifier_pattern",
                                        "identifier",
                                    ):
                                        pname = get_text(prop)
                                        self._record_require_import(
                                            pname, pname, source_mod, line
                                        )
                            continue

                if (
                    id_node
                    and id_node.type == "identifier"
                    and value_node
                    and value_node.type
                    in ("arrow_function", "function_expression")
                ):
                    name = get_text(id_node)
                    line = declarator.start_point.row + 1
                    end_line = declarator.end_point.row + 1
                    parent = self._current_qualname()
                    parent_name = None if parent == "<module>" else parent
                    definition = self._add_symbol(
                        name, "function", line, end_line, parent_name
                    )
                    self._scope.append(
                        (
                            definition.qualified_name,
                            definition.node_id,
                            "function",
                        )
                    )
                    visit(value_node)
                    self._scope.pop()
                    continue

            visit(declarator)

    def _record_require_import(
        self,
        local_name: str,
        symbol_name: Optional[str],
        source_module: str,
        line: int,
    ) -> None:
        import_id = _node_id(
            "import",
            self.path,
            line,
            f"{local_name}={source_module}.{symbol_name or ''}",
        )
        if self.graph.add_node(
            GraphNode(
                id=import_id,
                kind="import",
                name=symbol_name or local_name,
                path=self.path,
                line=line,
                metadata={
                    "local_name": local_name,
                    "module_name": source_module,
                    "symbol_name": symbol_name,
                    "alias": None,
                },
            )
        ):
            self.graph.add_edge(
                GraphEdge(
                    source=self.file_node_id,
                    target=import_id,
                    kind="imports",
                    metadata={"line": line},
                )
            )

        self.import_bindings.append(
            _ImportBinding(
                local_name=local_name,
                module_name=source_module,
                symbol_name=symbol_name,
                line=line,
                import_node_id=import_id,
            )
        )

    def _visit_call(self, node: Any, get_text: Any, visit: Any) -> None:
        fn = node.child_by_field_name("function")
        if not fn and node.children:
            fn = node.children[0]

        if fn:
            expression = get_text(fn)
            line = node.start_point.row + 1
            call_id = _node_id("call", self.path, line, expression)

            if self.graph.add_node(
                GraphNode(
                    id=call_id,
                    kind="call",
                    name=expression,
                    path=self.path,
                    line=line,
                    metadata={
                        "expression": expression,
                        "containing_qualname": self._current_qualname(),
                    },
                )
            ):
                self.graph.add_edge(
                    GraphEdge(
                        source=self._current_symbol_id(),
                        target=call_id,
                        kind="contains_call",
                        metadata={"line": line},
                    )
                )

            self.calls.append(
                _CallReference(
                    expression=expression,
                    path=self.path,
                    line=line,
                    containing_symbol_id=self._current_symbol_id(),
                    containing_qualname=self._current_qualname(),
                    node_id=call_id,
                )
            )

        for child in node.children:
            visit(child)

    def _visit_member(self, node: Any, get_text: Any, visit: Any) -> None:
        expression = get_text(node)
        line = node.start_point.row + 1
        attr_id = _node_id("attribute", self.path, line, expression)

        if self.graph.add_node(
            GraphNode(
                id=attr_id,
                kind="attribute_reference",
                name=expression,
                path=self.path,
                line=line,
                metadata={
                    "expression": expression,
                    "root": expression.split(".", 1)[0],
                    "containing_qualname": self._current_qualname(),
                },
            )
        ):
            self.graph.add_edge(
                GraphEdge(
                    source=self._current_symbol_id(),
                    target=attr_id,
                    kind="references_attribute",
                    metadata={"line": line},
                )
            )

        self.attributes.append(
            _AttributeReference(
                expression=expression,
                path=self.path,
                line=line,
                containing_symbol_id=self._current_symbol_id(),
                node_id=attr_id,
            )
        )

        for child in node.children:
            visit(child)


class DependencyGraphBuilder:
    """Build a bounded graph from a supplied read-only source snapshot."""

    def __init__(
        self,
        max_files: int = DEFAULT_MAX_FILES,
        max_nodes: int = DEFAULT_MAX_NODES,
        max_edges: int = DEFAULT_MAX_EDGES,
    ) -> None:
        self.max_files = max(1, int(max_files))
        self.max_nodes = max(1, int(max_nodes))
        self.max_edges = max(1, int(max_edges))

    def build(
        self,
        source_files: Mapping[str, str],
    ) -> DependencyGraph:
        graph = DependencyGraph(
            metadata={
                "max_files": self.max_files,
                "max_nodes": self.max_nodes,
                "max_edges": self.max_edges,
                "source_file_count": 0,
                "python_file_count": 0,
                "template_file_count": 0,
                "parsed_python_file_count": 0,
                "parse_error_count": 0,
                "node_limit_reached": False,
                "edge_limit_reached": False,
                "file_limit_reached": False,
                "nodes_skipped_by_limit": 0,
                "edges_skipped_by_limit": 0,
                "edges_skipped_missing_endpoint": 0,
            }
        )

        if not isinstance(source_files, Mapping):
            graph.metadata["input_invalid"] = True
            return graph

        normalized_files: dict[str, str] = {}

        for raw_path, content in source_files.items():
            if not isinstance(raw_path, str) or not isinstance(content, str):
                graph.metadata["invalid_source_entry_count"] = (
                    graph.metadata.get("invalid_source_entry_count", 0) + 1
                )
                continue

            path = _normalize_path(raw_path)
            if (
                not path
                or path == "."
                or path.startswith("/")
                or (len(path) > 1 and path[1] == ":")
                or ".." in path.split("/")
                or _is_ignored_path(path)
            ):
                graph.metadata["unsafe_or_ignored_path_count"] = (
                    graph.metadata.get("unsafe_or_ignored_path_count", 0)
                    + 1
                )
                continue

            normalized_files[path] = content

        ordered_paths = sorted(normalized_files)
        if len(ordered_paths) > self.max_files:
            graph.metadata["file_limit_reached"] = True
            graph.metadata["files_skipped_by_limit"] = (
                len(ordered_paths) - self.max_files
            )
            ordered_paths = ordered_paths[: self.max_files]

        normalized_files = {
            path: normalized_files[path] for path in ordered_paths
        }
        graph.metadata["source_file_count"] = len(normalized_files)

        file_nodes: dict[str, str] = {}
        analyzers: dict[str, _PythonFileAnalyzer] = {}
        module_to_paths: dict[str, list[str]] = defaultdict(list)
        parsed_trees: dict[str, ast.Module] = {}

        # First pass: create file nodes and parse source files.
        for path, content in normalized_files.items():
            extension = _extension(path)

            if extension not in SOURCE_EXTENSIONS:
                continue

            if extension in PYTHON_EXTENSIONS:
                kind = "python_file"
            elif extension in TEMPLATE_EXTENSIONS:
                kind = "template_file"
            else:
                kind = "file"

            file_id = _node_id("file", path, None, path)

            if not graph.add_node(
                GraphNode(
                    id=file_id,
                    kind=kind,
                    name=posixpath.basename(path),
                    path=path,
                    metadata={"extension": extension},
                )
            ):
                continue

            file_nodes[path] = file_id

            if extension == ".py":
                graph.metadata["python_file_count"] += 1
                module = _module_name(path)
                if module is not None:
                    module_to_paths[module].append(path)

                try:
                    tree = ast.parse(content, filename=path)
                except (SyntaxError, ValueError, TypeError) as exc:
                    logger.warning(
                        f"[DeepSearch] Failed to parse Python file '{path}': {exc}"
                    )
                    graph.metadata["parse_error_count"] += 1
                    graph.add_unresolved(
                        UnresolvedReference(
                            source=file_id,
                            name=path,
                            kind="parse_error",
                            path=path,
                            line=getattr(exc, "lineno", None),
                            reason="python_source_parse_failed",
                            metadata={"error_type": type(exc).__name__},
                        )
                    )
                    continue

                parsed_trees[path] = tree
                analyzer = _PythonFileAnalyzer(path, graph, file_id)
                analyzer.visit(tree)
                analyzers[path] = analyzer
                graph.metadata["parsed_python_file_count"] += 1

            elif extension in TEMPLATE_EXTENSIONS:
                graph.metadata["template_file_count"] += 1
                self._analyze_template(path, content, graph, file_id)

            elif extension in TYPESCRIPT_EXTENSIONS | JAVASCRIPT_EXTENSIONS:
                if extension in TYPESCRIPT_EXTENSIONS:
                    graph.metadata["typescript_file_count"] = (
                        graph.metadata.get("typescript_file_count", 0) + 1
                    )
                else:
                    graph.metadata["javascript_file_count"] = (
                        graph.metadata.get("javascript_file_count", 0) + 1
                    )

                is_tsx = extension in {".tsx", ".jsx"}
                parser = _get_ts_parser(tsx=is_tsx) or _get_ts_parser(tsx=False)

                if parser is None:
                    logger.warning(
                        f"[DeepSearch] Tree-sitter parser not available for '{path}'."
                    )
                    graph.metadata["parse_error_count"] = (
                        graph.metadata.get("parse_error_count", 0) + 1
                    )
                    graph.add_unresolved(
                        UnresolvedReference(
                            source=file_id,
                            name=path,
                            kind="parse_error",
                            path=path,
                            reason="tree_sitter_parser_not_available",
                        )
                    )
                    continue

                try:
                    source_bytes = content.encode("utf8")
                    tree = parser.parse(source_bytes)
                except Exception as exc:
                    logger.warning(
                        f"[DeepSearch] Failed to parse TypeScript/JavaScript file '{path}': {exc}"
                    )
                    graph.metadata["parse_error_count"] = (
                        graph.metadata.get("parse_error_count", 0) + 1
                    )
                    graph.add_unresolved(
                        UnresolvedReference(
                            source=file_id,
                            name=path,
                            kind="parse_error",
                            path=path,
                            reason="ts_source_parse_failed",
                            metadata={"error_type": type(exc).__name__},
                        )
                    )
                    continue

                ts_analyzer = _TreeSitterFileAnalyzer(path, graph, file_id)
                ts_analyzer.analyze(tree.root_node, source_bytes)
                analyzers[path] = ts_analyzer
                graph.metadata["parsed_ts_file_count"] = (
                    graph.metadata.get("parsed_ts_file_count", 0) + 1
                )

        # Resolve import targets with one shared module index.
        module_index: dict[str, str] = {
            module: paths[0]
            for module, paths in module_to_paths.items()
            if len(paths) == 1
        }

        ambiguous_modules = {
            module: paths
            for module, paths in module_to_paths.items()
            if len(paths) > 1
        }

        graph.metadata["ambiguous_module_count"] = len(ambiguous_modules)

        resolved_bindings: dict[str, dict[str, list[tuple[str, str]]]] = {}
        for path, analyzer in analyzers.items():
            resolved_bindings[path] = self._resolve_imports(
                path=path,
                analyzer=analyzer,
                module_index=module_index,
                ambiguous_modules=ambiguous_modules,
                graph=graph,
                file_nodes=file_nodes,
            )

        # Resolve local/imported calls and local attribute evidence.
        definitions_by_path: dict[str, list[_Definition]] = {
            path: analyzer.definitions
            for path, analyzer in analyzers.items()
        }

        definitions_by_module_name: dict[
            tuple[str, str], list[_Definition]
        ] = defaultdict(list)

        for path, definitions in definitions_by_path.items():
            module = _module_name(path)
            if module is None:
                continue
            for definition in definitions:
                definitions_by_module_name[
                    (module, definition.name)
                ].append(definition)

        for path, analyzer in analyzers.items():
            bindings = resolved_bindings.get(path, {})
            module = _module_name(path) or ""

            self._resolve_calls(
                path=path,
                analyzer=analyzer,
                bindings=bindings,
                module_name=module,
                definitions_by_path=definitions_by_path,
                definitions_by_module_name=definitions_by_module_name,
                graph=graph,
            )

            self._record_unresolved_attributes(analyzer, graph)

        # Connect Python render calls to the exact template path when that
        # path can be uniquely resolved in the supplied snapshot.
        template_references_by_path: dict[
            str, list[_TemplateReference]
        ] = {}
        for path, content in normalized_files.items():
            if path in file_nodes and _extension(path) in TEMPLATE_EXTENSIONS:
                template_references_by_path[path] = self._get_template_refs(
                    path, content, graph, file_nodes[path]
                )

        self._resolve_template_renders(
            analyzers=analyzers,
            template_paths=[
                path
                for path in file_nodes
                if _extension(path) in TEMPLATE_EXTENSIONS
            ],
            template_references_by_path=template_references_by_path,
            graph=graph,
        )

        graph.metadata.update(
            {
                "node_count": len(graph.nodes),
                "edge_count": len(graph.edges),
                "unresolved_reference_count": len(
                    graph.unresolved_references
                ),
                "ambiguous_module_paths": {
                    module: sorted(paths)
                    for module, paths in ambiguous_modules.items()
                },
            }
        )

        logger.info(
            "dependency_graph_built",
            extra={
                "source_file_count": graph.metadata["source_file_count"],
                "node_count": len(graph.nodes),
                "edge_count": len(graph.edges),
                "unresolved_reference_count": len(
                    graph.unresolved_references
                ),
                "node_limit_reached": graph.metadata[
                    "node_limit_reached"
                ],
                "edge_limit_reached": graph.metadata[
                    "edge_limit_reached"
                ],
                "file_limit_reached": graph.metadata[
                    "file_limit_reached"
                ],
            },
        )

        return graph

    def _resolve_imports(
        self,
        path: str,
        analyzer: _PythonFileAnalyzer | _TreeSitterFileAnalyzer,
        module_index: Mapping[str, str],
        ambiguous_modules: Mapping[str, list[str]],
        graph: DependencyGraph,
        file_nodes: Optional[Mapping[str, str]] = None,
    ) -> dict[str, list[tuple[str, str]]]:
        """
        Resolve import bindings.

        Result:
            local name -> [(target module path, target symbol node id or "")]

        An empty symbol id means the import resolved to a module, not a symbol.
        """
        result: dict[str, list[tuple[str, str]]] = defaultdict(list)

        if _extension(path) in TYPESCRIPT_EXTENSIONS | JAVASCRIPT_EXTENSIONS:
            available = file_nodes or {}
            for binding in analyzer.import_bindings:
                target_path = _resolve_ts_import_path(
                    current_path=path,
                    import_module=binding.module_name,
                    available_paths=available,
                )

                if target_path is None:
                    graph.add_unresolved(
                        UnresolvedReference(
                            source=binding.import_node_id,
                            name=binding.module_name,
                            kind="unresolved_import",
                            path=path,
                            line=binding.line,
                            reason="import_target_not_in_source_snapshot",
                        )
                    )
                    continue

                if binding.symbol_name:
                    target_symbol_id = self._find_definition_id(
                        target_path,
                        binding.symbol_name,
                        graph,
                    )
                else:
                    target_symbol_id = ""

                target_file_id = _node_id(
                    "file",
                    target_path,
                    None,
                    target_path,
                )

                graph.add_edge(
                    GraphEdge(
                        source=binding.import_node_id,
                        target=target_file_id,
                        kind="imports_module",
                        metadata={
                            "imported_module": binding.module_name,
                            "line": binding.line,
                        },
                    )
                )

                if target_symbol_id and target_symbol_id in graph.nodes:
                    graph.add_edge(
                        GraphEdge(
                            source=binding.import_node_id,
                            target=target_symbol_id,
                            kind="imports_symbol",
                            metadata={"line": binding.line},
                        )
                    )

                result[binding.local_name].append(
                    (target_path, target_symbol_id)
                )

            return result

        for binding in analyzer.import_bindings:
            absolute_module = self._absolute_import_module(
                current_path=path,
                imported_module=binding.module_name,
            )

            if not absolute_module:
                graph.add_unresolved(
                    UnresolvedReference(
                        source=binding.import_node_id,
                        name=binding.module_name,
                        kind="unresolved_import",
                        path=path,
                        line=binding.line,
                        reason="relative_import_could_not_be_resolved",
                    )
                )
                continue

            target_path = module_index.get(absolute_module)

            # `from package import symbol` can refer to a symbol in package
            # or to a submodule package.symbol. Prefer a direct submodule
            # only when it exists unambiguously.
            if binding.symbol_name:
                submodule_name = (
                    f"{absolute_module}.{binding.symbol_name}"
                    if absolute_module
                    else binding.symbol_name
                )
                submodule_path = module_index.get(submodule_name)

                if target_path is None and submodule_path is not None:
                    target_path = submodule_path
                    target_symbol_id = ""
                elif target_path is not None:
                    target_symbol_id = self._find_definition_id(
                        target_path,
                        binding.symbol_name,
                        graph,
                    )
                    if not target_symbol_id and submodule_path:
                        target_path = submodule_path
                        target_symbol_id = ""
                else:
                    target_symbol_id = ""
            else:
                target_symbol_id = ""

            if target_path is None:
                if absolute_module in ambiguous_modules:
                    reason = "ambiguous_import_module"
                    paths = ambiguous_modules[absolute_module]
                else:
                    reason = "import_target_not_in_source_snapshot"
                    paths = []

                graph.add_unresolved(
                    UnresolvedReference(
                        source=binding.import_node_id,
                        name=absolute_module,
                        kind="unresolved_import",
                        path=path,
                        line=binding.line,
                        reason=reason,
                        metadata={"candidate_paths": paths},
                    )
                )
                continue

            target_file_id = _node_id(
                "file",
                target_path,
                None,
                target_path,
            )

            graph.add_edge(
                GraphEdge(
                    source=binding.import_node_id,
                    target=target_file_id,
                    kind="imports_module",
                    metadata={
                        "imported_module": absolute_module,
                        "line": binding.line,
                    },
                )
            )

            if target_symbol_id and target_symbol_id in graph.nodes:
                graph.add_edge(
                    GraphEdge(
                        source=binding.import_node_id,
                        target=target_symbol_id,
                        kind="imports_symbol",
                        metadata={"line": binding.line},
                    )
                )

            result[binding.local_name].append(
                (target_path, target_symbol_id)
            )

        return result

    @staticmethod
    def _absolute_import_module(
        current_path: str,
        imported_module: str,
    ) -> Optional[str]:
        if not imported_module.startswith("."):
            return imported_module.strip(".") or None

        level = len(imported_module) - len(imported_module.lstrip("."))
        remainder = imported_module[level:].strip(".")
        package = _package_name(current_path)
        package_parts = package.split(".") if package else []

        # One leading dot means the current package; each additional dot
        # ascends one package level.
        ascend = level - 1
        if ascend > len(package_parts):
            return None

        if ascend:
            package_parts = package_parts[: len(package_parts) - ascend]

        if remainder:
            package_parts.extend(remainder.split("."))

        resolved = ".".join(part for part in package_parts if part)
        return resolved or None

    @staticmethod
    def _find_definition_id(
        target_path: str,
        symbol_name: str,
        graph: DependencyGraph,
    ) -> str:
        candidates = [
            node.id
            for node in graph.nodes.values()
            if node.path == target_path
            and node.kind in {
                "function",
                "method",
                "class",
                "interface",
                "type",
                "property",
            }
            and node.name == symbol_name
        ]

        # Multiple same-named nested definitions are ambiguous unless there
        # is exactly one definition.
        return candidates[0] if len(candidates) == 1 else ""

    def _resolve_calls(
        self,
        path: str,
        analyzer: _PythonFileAnalyzer,
        bindings: Mapping[str, list[tuple[str, str]]],
        module_name: str,
        definitions_by_path: Mapping[str, list[_Definition]],
        definitions_by_module_name: Mapping[
            tuple[str, str], list[_Definition]
        ],
        graph: DependencyGraph,
    ) -> None:
        local_definitions = definitions_by_path.get(path, [])

        for call in analyzer.calls:
            expression = call.expression
            parts = expression.split(".")
            candidates: list[_Definition] = []

            if len(parts) == 1:
                name = parts[0]

                # Prefer a definition in the same lexical scope. A unique
                # same-file definition is the only fallback if scope matching
                # cannot identify one exact target.
                scoped = [
                    definition
                    for definition in local_definitions
                    if definition.name == name
                    and (
                        call.containing_qualname == definition.qualified_name
                        or call.containing_qualname.startswith(
                            definition.qualified_name + "."
                        )
                    )
                ]

                if len(scoped) == 1:
                    candidates = scoped
                else:
                    same_file = [
                        definition
                        for definition in local_definitions
                        if definition.name == name
                        and definition.kind in {"function", "method"}
                    ]
                    if len(same_file) == 1:
                        candidates = same_file

                if not candidates and name in bindings:
                    imported_targets = bindings[name]
                    symbol_candidates: list[str] = []

                    for target_path, target_symbol_id in imported_targets:
                        if target_symbol_id:
                            symbol_candidates.append(target_symbol_id)
                        else:
                            symbol_candidates.extend(
                                definition.node_id
                                for definition in definitions_by_path.get(
                                    target_path, []
                                )
                                if definition.name == name
                            )

                    unique_ids = sorted(set(symbol_candidates))
                    if len(unique_ids) == 1:
                        target = graph.nodes.get(unique_ids[0])
                        if target:
                            graph.add_edge(
                                GraphEdge(
                                    source=call.node_id,
                                    target=target.id,
                                    kind="calls",
                                    metadata={
                                        "expression": expression,
                                        "resolution": "imported_symbol",
                                    },
                                )
                            )
                            continue

            elif len(parts) >= 2:
                root, member = parts[0], parts[-1]

                # Resolve self.method() or this.method() only inside the containing class.
                if root in ("self", "this"):
                    containing_class = call.containing_qualname.rsplit(
                        ".", 1
                    )[0]
                    scoped = [
                        definition
                        for definition in local_definitions
                        if definition.name == member
                        and definition.kind == "method"
                        and definition.qualified_name.startswith(
                            containing_class + "."
                        )
                    ]
                    if len(scoped) == 1:
                        candidates = scoped

                # Resolve a class method only if the class name uniquely
                # identifies a local or imported class.
                if not candidates:
                    class_candidates = [
                        definition
                        for definition in local_definitions
                        if definition.name == root
                        and definition.kind == "class"
                    ]

                    if len(class_candidates) == 1:
                        class_name = class_candidates[0].qualified_name
                        candidates = [
                            definition
                            for definition in local_definitions
                            if definition.name == member
                            and definition.kind == "method"
                            and definition.qualified_name
                            == f"{class_name}.{member}"
                        ]

                # Resolve module_alias.function() only when the import
                # binding identifies exactly one source module.
                if not candidates and root in bindings:
                    imported = bindings[root]
                    target_paths = {target_path for target_path, _ in imported}

                    if len(target_paths) == 1:
                        target_path = next(iter(target_paths))
                        candidates = [
                            definition
                            for definition in definitions_by_path.get(
                                target_path, []
                            )
                            if definition.name == member
                            and definition.kind in {"function", "method"}
                        ]

            candidate_ids = sorted(
                {definition.node_id for definition in candidates}
            )

            if len(candidate_ids) == 1:
                graph.add_edge(
                    GraphEdge(
                        source=call.node_id,
                        target=candidate_ids[0],
                        kind="calls",
                        metadata={
                            "expression": expression,
                            "resolution": "unambiguous_static_call",
                        },
                    )
                )
            else:
                graph.add_unresolved(
                    UnresolvedReference(
                        source=call.node_id,
                        name=expression,
                        kind="unresolved_call",
                        path=path,
                        line=call.line,
                        reason=(
                            "ambiguous_call_target"
                            if len(candidate_ids) > 1
                            else "call_target_not_resolved"
                        ),
                        metadata={
                            "candidate_ids": candidate_ids,
                            "module": module_name,
                        },
                    )
                )

    @staticmethod
    def _record_unresolved_attributes(
        analyzer: _PythonFileAnalyzer,
        graph: DependencyGraph,
    ) -> None:
        for reference in analyzer.attributes:
            # A syntactic attribute is evidence of usage, not proof of its
            # runtime owner or of a model/schema field.
            graph.add_unresolved(
                UnresolvedReference(
                    source=reference.node_id,
                    name=reference.expression,
                    kind="unresolved_attribute",
                    path=reference.path,
                    line=reference.line,
                    reason="attribute_owner_not_statically_proven",
                    metadata={
                        "containing_symbol_id": (
                            reference.containing_symbol_id
                        )
                    },
                )
            )

    def _analyze_template(
        self,
        path: str,
        content: str,
        graph: DependencyGraph,
        file_node_id: str,
    ) -> None:
        """Create template reference nodes; resolution occurs after parsing."""
        self._get_template_refs(path, content, graph, file_node_id)

    def _get_template_refs(
        self,
        path: str,
        content: str,
        graph: DependencyGraph,
        file_node_id: str,
    ) -> list[_TemplateReference]:
        references: list[_TemplateReference] = []
        seen: set[tuple[int, str]] = set()

        for line_number, line_text in enumerate(content.splitlines(), start=1):
            for match in TEMPLATE_REFERENCE_RE.finditer(line_text):
                expression = _template_attribute_expression(match)
                if "." not in expression:
                    continue

                key = (line_number, expression)
                if key in seen:
                    continue
                seen.add(key)

                reference_id = _node_id(
                    "template_ref",
                    path,
                    line_number,
                    expression,
                )

                if graph.add_node(
                    GraphNode(
                        id=reference_id,
                        kind="template_attribute_reference",
                        name=expression,
                        path=path,
                        line=line_number,
                        metadata={
                            "expression": expression,
                            "root": expression.split(".", 1)[0],
                        },
                    )
                ):
                    graph.add_edge(
                        GraphEdge(
                            source=file_node_id,
                            target=reference_id,
                            kind="contains_template_reference",
                            metadata={"line": line_number},
                        )
                    )

                references.append(
                    _TemplateReference(
                        expression=expression,
                        root=expression.split(".", 1)[0],
                        path=path,
                        line=line_number,
                        node_id=reference_id,
                    )
                )

                graph.add_unresolved(
                    UnresolvedReference(
                        source=reference_id,
                        name=expression,
                        kind="template_attribute_reference",
                        path=path,
                        line=line_number,
                        reason="template_attribute_owner_not_proven",
                    )
                )

        return references

    def _resolve_template_renders(
        self,
        analyzers: Mapping[str, _PythonFileAnalyzer],
        template_paths: list[str],
        template_references_by_path: Mapping[
            str, list[_TemplateReference]
        ],
        graph: DependencyGraph,
    ) -> None:
        """Connect render callers to templates and verified context roots."""
        templates_by_name: dict[str, list[str]] = defaultdict(list)

        for template_path in template_paths:
            templates_by_name[posixpath.basename(template_path)].append(
                template_path
            )

        for analyzer in analyzers.values():
            for render in analyzer.template_renders:
                basename = posixpath.basename(render.template_name)
                candidates = templates_by_name.get(basename, [])

                if len(candidates) != 1:
                    graph.add_unresolved(
                        UnresolvedReference(
                            source=render.node_id,
                            name=render.template_name,
                            kind="template_render",
                            path=render.path,
                            line=render.line,
                            reason=(
                                "ambiguous_template_path"
                                if candidates
                                else "template_not_in_source_snapshot"
                            ),
                            metadata={"candidate_paths": sorted(candidates)},
                        )
                    )
                    continue

                template_path = candidates[0]
                template_file_id = _node_id(
                    "file",
                    template_path,
                    None,
                    template_path,
                )

                graph.add_edge(
                    GraphEdge(
                        source=render.node_id,
                        target=template_file_id,
                        kind="renders_template",
                        metadata={
                            "template_name": render.template_name,
                            "line": render.line,
                        },
                    )
                )

                template_refs = template_references_by_path.get(
                    template_path, []
                )

                for context_name, source_expression in (
                    render.context_bindings.items()
                ):
                    matching_refs = [
                        reference
                        for reference in template_refs
                        if reference.root == context_name
                    ]

                    if not matching_refs:
                        continue

                    # This edge establishes that the renderer supplies a
                    # context key used by the template. It does not prove
                    # that the supplied expression is a particular model.
                    for reference in matching_refs:
                        graph.add_edge(
                            GraphEdge(
                                source=render.node_id,
                                target=reference.node_id,
                                kind="supplies_template_context",
                                metadata={
                                    "context_name": context_name,
                                    "source_expression": source_expression,
                                    "line": render.line,
                                    "template_path": template_path,
                                    "evidence": (
                                        "explicit_render_template_keyword"
                                    ),
                                },
                            )
                        )


def build_dependency_graph(
    source_files: Mapping[str, str],
    max_files: int = DEFAULT_MAX_FILES,
    max_nodes: int = DEFAULT_MAX_NODES,
    max_edges: int = DEFAULT_MAX_EDGES,
) -> DependencyGraph:
    """Public entry point retained for existing Deep Search callers."""
    return DependencyGraphBuilder(
        max_files=max_files,
        max_nodes=max_nodes,
        max_edges=max_edges,
    ).build(source_files)
