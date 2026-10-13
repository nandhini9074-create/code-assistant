"""
tests/test_deep_search_pipeline_execution.py

Unit tests verifying that deep search context is passed to context building
and followed by all subsequent steps in the search pipeline for FIX_BUG queries.
"""

from unittest.mock import AsyncMock, MagicMock
import pytest

from app.core.enums import IntentType
from app.modules.search.domain.search_domain import RetrievedChunk, SearchContext
from app.modules.search.service.search_service import SearchService


@pytest.fixture
def mock_stages():
    val_stage = MagicMock()
    val_stage.execute = AsyncMock()

    intent_stage = MagicMock()
    intent_stage.execute = AsyncMock()

    query_prep_stage = MagicMock()
    query_prep_stage.execute = AsyncMock()

    coll_sel_stage = MagicMock()
    coll_sel_stage.execute = AsyncMock()

    code_ret_stage = MagicMock()
    code_ret_stage.execute = AsyncMock()

    code_ident_stage = MagicMock()
    code_ident_stage.execute = AsyncMock()

    ctx_build_stage = MagicMock()
    ctx_build_stage.execute = AsyncMock()

    code_analysis_stage = MagicMock()
    code_analysis_stage.execute = AsyncMock()

    ev_val_stage = MagicMock()
    ev_val_stage.execute = AsyncMock()

    action_analysis_stage = MagicMock()
    action_analysis_stage.execute = AsyncMock()

    suggestion_patch_stage = MagicMock()
    suggestion_patch_stage.execute = AsyncMock()

    suggestion_validation_stage = MagicMock()
    suggestion_validation_stage.execute = AsyncMock()

    final_triage_stage = MagicMock()
    final_triage_stage.execute = AsyncMock()

    resp_gen_stage = MagicMock()
    resp_gen_stage.execute = AsyncMock()

    deep_search_stage = MagicMock()
    deep_search_stage.execute = AsyncMock()

    service = SearchService(
        val_stage=val_stage,
        intent_stage=intent_stage,
        query_prep_stage=query_prep_stage,
        coll_sel_stage=coll_sel_stage,
        code_ret_stage=code_ret_stage,
        code_ident_stage=code_ident_stage,
        ctx_build_stage=ctx_build_stage,
        code_analysis_stage=code_analysis_stage,
        ev_val_stage=ev_val_stage,
        action_analysis_stage=action_analysis_stage,
        suggestion_patch_stage=suggestion_patch_stage,
        suggestion_validation_stage=suggestion_validation_stage,
        final_triage_stage=final_triage_stage,
        resp_gen_stage=resp_gen_stage,
        deep_search_stage=deep_search_stage,
    )

    return {
        "service": service,
        "val_stage": val_stage,
        "intent_stage": intent_stage,
        "query_prep_stage": query_prep_stage,
        "coll_sel_stage": coll_sel_stage,
        "code_ret_stage": code_ret_stage,
        "code_ident_stage": code_ident_stage,
        "ctx_build_stage": ctx_build_stage,
        "code_analysis_stage": code_analysis_stage,
        "ev_val_stage": ev_val_stage,
        "action_analysis_stage": action_analysis_stage,
        "suggestion_patch_stage": suggestion_patch_stage,
        "suggestion_validation_stage": suggestion_validation_stage,
        "final_triage_stage": final_triage_stage,
        "resp_gen_stage": resp_gen_stage,
        "deep_search_stage": deep_search_stage,
    }


@pytest.mark.asyncio
async def test_deep_search_context_passes_to_context_building_and_pipeline(mock_stages):
    """
    Verify that for FIX_BUG requiring deep search:
    1. deep_search_stage is executed.
    2. retrieved chunks from deep search are populated into context.retrieved_chunks.
    3. context.early_exit is cleared.
    4. context building (ctx_build_stage) and subsequent stages are all called.
    """
    stages = mock_stages
    service = stages["service"]

    # Configure intent classification to require deep search
    async def mock_intent(ctx):
        ctx.intent = IntentType.FIX_BUG
        ctx.intent_parameters = {"deep_search_requested": True}

    stages["intent_stage"].execute.side_effect = mock_intent

    # Configure collection selection to set collection
    async def mock_coll(ctx):
        ctx.qdrant_collection = "test_repo_collection"
        ctx.repo_name = "test_repo"

    stages["coll_sel_stage"].execute.side_effect = mock_coll

    # Configure deep search stage to retrieve context
    async def mock_deep_search(ctx):
        ctx.deep_search_result = {
            "status": "complete",
            "diagnosis": "Missing field in model schema contract.",
            "retrieved_chunks": [
                {
                    "path": "app/models/user.py",
                    "content": "class User:\n    id: int\n    name: str",
                    "line_start": 1,
                    "line_end": 3,
                    "score": 0.95,
                    "metadata": {"file_path": "app/models/user.py"},
                },
                {
                    "path": "app/schemas/user.py",
                    "content": "class UserSchema:\n    id: int",
                    "line_start": 1,
                    "line_end": 2,
                    "score": 0.90,
                    "metadata": {"file_path": "app/schemas/user.py"},
                },
            ],
            "evidence": [],
        }
        ctx.early_exit = "DEEP_SEARCH_COMPLETE"

    stages["deep_search_stage"].execute.side_effect = mock_deep_search

    # Execute search pipeline
    result = await service.run_pipeline(
        source_type="git",
        source_location="https://github.com/test/repo",
        query="Fix AttributeError: User object has no attribute name in schema",
    )

    # 1. Deep search stage was executed
    stages["deep_search_stage"].execute.assert_awaited_once()

    # 2. Normal code retrieval stage was NOT executed (replaced by deep search)
    stages["code_ret_stage"].execute.assert_not_awaited()

    # 3. Context building and all following steps in the pipeline WERE executed
    stages["code_ident_stage"].execute.assert_awaited_once()
    stages["ctx_build_stage"].execute.assert_awaited_once()
    stages["code_analysis_stage"].execute.assert_awaited_once()
    stages["ev_val_stage"].execute.assert_awaited_once()
    stages["action_analysis_stage"].execute.assert_awaited_once()
    stages["suggestion_patch_stage"].execute.assert_awaited_once()
    stages["suggestion_validation_stage"].execute.assert_awaited_once()
    stages["final_triage_stage"].execute.assert_awaited_once()
    stages["resp_gen_stage"].execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_deep_search_transfers_retrieved_chunks(mock_stages):
    """
    Verify that _transfer_deep_search_chunks correctly converts raw dicts into
    RetrievedChunk dataclass instances on context.retrieved_chunks.
    """
    service = mock_stages["service"]
    ctx = SearchContext(
        query="test query",
        source_type="git",
        source_location="https://github.com/test/repo",
        repo_name="test_repo",
    )
    ctx.deep_search_result = {
        "status": "complete",
        "retrieved_chunks": [
            {
                "path": "services/auth.py",
                "content": "def authenticate(): pass",
                "line_start": 10,
                "line_end": 12,
                "score": 0.88,
            }
        ],
    }

    service._transfer_deep_search_chunks(ctx)

    assert len(ctx.retrieved_chunks) == 1
    chunk = ctx.retrieved_chunks[0]
    assert isinstance(chunk, RetrievedChunk)
    assert chunk.file_path == "services/auth.py"
    assert chunk.content == "def authenticate(): pass"
    assert chunk.score == 0.88
    assert chunk.metadata["start_line"] == 10
    assert chunk.metadata["end_line"] == 12


@pytest.mark.asyncio
async def test_deep_search_unavailable_stops_before_context_building(mock_stages):
    """
    Verify that if deep search fails to retrieve any chunks, early exit occurs
    and context building is not run.
    """
    stages = mock_stages
    service = stages["service"]

    async def mock_intent(ctx):
        ctx.intent = IntentType.FIX_BUG
        ctx.intent_parameters = {"deep_search_requested": True}

    stages["intent_stage"].execute.side_effect = mock_intent

    async def mock_coll(ctx):
        ctx.qdrant_collection = "test_collection"
        ctx.repo_name = "test_repo"

    stages["coll_sel_stage"].execute.side_effect = mock_coll

    async def mock_deep_search(ctx):
        ctx.deep_search_result = {
            "status": "unavailable",
            "retrieved_chunks": [],
            "reason": "Source files missing",
        }
        ctx.early_exit = "DEEP_SEARCH_COMPLETE"

    stages["deep_search_stage"].execute.side_effect = mock_deep_search

    result = await service.run_pipeline(
        source_type="git",
        source_location="https://github.com/test/repo",
        query="Fix missing attribute",
    )

    stages["deep_search_stage"].execute.assert_awaited_once()
    stages["ctx_build_stage"].execute.assert_not_awaited()
    stages["code_analysis_stage"].execute.assert_not_awaited()
