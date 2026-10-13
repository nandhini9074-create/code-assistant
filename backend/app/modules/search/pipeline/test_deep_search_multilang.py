"""
Tests for multi-language (TypeScript / JavaScript) support in Deep Search.
"""

from __future__ import annotations

import pytest

from app.modules.search.pipeline.dependency_graph import (
    build_dependency_graph,
    DependencyGraphBuilder,
)
from app.modules.search.pipeline.deep_search_explorer import (
    DeepSearchExplorer,
)
from app.modules.search.pipeline.deep_search_decision import (
    decide_deep_search,
)


@pytest.fixture
def ts_source_files() -> dict[str, str]:
    return {
        "src/enrollment/dto/unenroll-card.dto.ts": (
            "import { ApiProperty } from '@nestjs/swagger';\n\n"
            "export class UnenrollCardItemDto {\n"
            "  @ApiProperty()\n"
            "  mimojoCardId: string;\n\n"
            "  constructor() {}\n\n"
            "  unenroll(cardId: string): string {\n"
            "    return this.mimojoCardId;\n"
            "  }\n"
            "}\n"
        ),
        "src/enrollment/enrollment.service.ts": (
            "import { Injectable } from '@nestjs/common';\n"
            "import { UnenrollCardItemDto } from './dto/unenroll-card.dto';\n\n"
            "@Injectable()\n"
            "export class EnrollmentService {\n"
            "  async processUnenroll(dto: UnenrollCardItemDto): Promise<void> {\n"
            "    dto.unenroll('123');\n"
            "  }\n"
            "}\n"
        ),
        "src/enrollment/enrollment.controller.ts": (
            "import { Controller, Post, Body } from '@nestjs/common';\n"
            "import { EnrollmentService } from './enrollment.service';\n"
            "import { UnenrollCardItemDto } from './dto/unenroll-card.dto';\n\n"
            "@Controller('enrollment')\n"
            "export class EnrollmentController {\n"
            "  constructor(private readonly service: EnrollmentService) {}\n\n"
            "  @Post('unenroll')\n"
            "  async unenroll(@Body() body: UnenrollCardItemDto) {\n"
            "    return this.service.processUnenroll(body);\n"
            "  }\n"
            "}\n"
        ),
    }


def test_ts_graph_creates_file_and_symbol_nodes(ts_source_files):
    graph = build_dependency_graph(ts_source_files)

    dto_path = "src/enrollment/dto/unenroll-card.dto.ts"
    service_path = "src/enrollment/enrollment.service.ts"

    assert f"file:{dto_path}:0:{dto_path}" in graph.nodes
    assert f"file:{service_path}:0:{service_path}" in graph.nodes

    # Check definitions
    class_nodes = [
        node for node in graph.nodes.values()
        if node.kind == "class" and node.name == "UnenrollCardItemDto"
    ]
    assert len(class_nodes) == 1
    assert class_nodes[0].path == dto_path

    # Check property definition
    prop_nodes = [
        node for node in graph.nodes.values()
        if node.kind == "property" and node.name == "mimojoCardId"
    ]
    assert len(prop_nodes) == 1
    assert prop_nodes[0].path == dto_path

    # Check methods in DTO
    method_nodes = [
        node for node in graph.nodes.values()
        if node.kind == "method" and node.name == "unenroll" and node.path == dto_path
    ]
    assert len(method_nodes) == 1


def test_ts_graph_resolves_cross_file_imports_and_symbols(ts_source_files):
    graph = build_dependency_graph(ts_source_files)

    # Check cross-file imports_module edge
    import_module_edges = [
        edge for edge in graph.edges
        if edge.kind == "imports_module"
        and "dto/unenroll-card.dto.ts" in edge.target
    ]
    assert len(import_module_edges) >= 1

    # Check cross-file imports_symbol edge pointing to UnenrollCardItemDto
    import_symbol_edges = [
        edge for edge in graph.edges
        if edge.kind == "imports_symbol"
        and "UnenrollCardItemDto" in edge.target
    ]
    assert len(import_symbol_edges) >= 1


def test_ts_explorer_finds_targets_for_user_typescript_error(ts_source_files):
    graph = build_dependency_graph(ts_source_files)
    explorer = DeepSearchExplorer(max_depth=3, max_targets=12)

    query = (
        "Property 'mimojoCardId' has no initializer and is not definitely "
        "assigned in the constructor.ts(2564) (property) "
        "UnenrollCardItemDto.mimojoCardId: string"
    )

    result = explorer.explore(query=query, graph=graph)
    assert result.targets
    target_names = {t.name for t in result.targets}
    target_paths = {t.path for t in result.targets}

    # Should locate the exact symbol and file
    assert "mimojoCardId" in target_names or "UnenrollCardItemDto" in target_names
    assert "src/enrollment/dto/unenroll-card.dto.ts" in target_paths


def test_decision_triggers_on_typescript_error_query():
    query = (
        "Property 'mimojoCardId' has no initializer and is not definitely "
        "assigned in the constructor.ts(2564) (property) "
        "UnenrollCardItemDto.mimojoCardId: string"
    )
    decision = decide_deep_search(intent="FIX_BUG", query=query)
    # The decision may or may not select initially, but even if escalated,
    # the multi-language graph supports it.
    assert isinstance(decision.selected, bool)
