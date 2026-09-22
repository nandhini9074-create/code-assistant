"""
tests/unit/search/test_collection_selection.py

Unit tests for CollectionSelectionStage and repo_name normalization logic.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.search.domain.search_domain import SearchContext
from app.modules.search.pipeline.collection_selection import (
    CollectionSelectionStage,
    parse_and_normalize_repo_input,
)


def test_parse_and_normalize_owner_repo_format():
    """Format 1: ownername_repositoryname -> repo_ownername_repositoryname."""
    coll, owner, repo = parse_and_normalize_repo_input(
        "nandhini9074_create_demo10_transaction"
    )
    assert coll == "repo_nandhini9074_create_demo10_transaction"
    assert owner == "nandhini9074"
    assert repo == "create_demo10_transaction"


def test_parse_and_normalize_repository_only_format():
    """Format 2: repositoryname -> repo_local_repositoryname."""
    coll, owner, repo = parse_and_normalize_repo_input("demo10")
    assert coll == "repo_local_demo10"
    assert owner is None
    assert repo == "demo10"


def test_parse_and_normalize_slash_format():
    """Slash format: owner/repo -> repo_owner_repo."""
    coll, owner, repo = parse_and_normalize_repo_input(
        "octocat/Hello-World"
    )
    assert coll == "repo_octocat_hello_world"
    assert owner == "octocat"
    assert repo == "hello_world"


def test_parse_and_normalize_prefixed_repo_local():
    """Already prefixed repo_local_ repository."""
    coll, owner, repo = parse_and_normalize_repo_input(
        "repo_local_my_project"
    )
    assert coll == "repo_local_my_project"
    assert owner is None
    assert repo == "my_project"


def test_parse_and_normalize_prefixed_repo_owner():
    """Already prefixed repo_ owner repository."""
    coll, owner, repo = parse_and_normalize_repo_input(
        "repo_owner_my_project"
    )
    assert coll == "repo_owner_my_project"
    assert owner == "owner"
    assert repo == "my_project"


def test_parse_and_normalize_disambiguation_via_available_collections():
    """If repository name has underscores and is local, resolves via available collections."""
    available = ["repo_local_create_demo10_transaction"]
    coll, owner, repo = parse_and_normalize_repo_input(
        "create_demo10_transaction",
        available_collections=available,
    )
    assert coll == "repo_local_create_demo10_transaction"
    assert owner is None
    assert repo == "create_demo10_transaction"


@pytest.mark.asyncio
async def test_stage_owner_repo_format_selection():
    """Verify CollectionSelectionStage sets resolved collection, owner, and repo without repo_id."""
    stage = CollectionSelectionStage()
    context = SearchContext(
        repo_name="nandhini9074_create_demo10_transaction",
        query="test query",
    )
    assert context.repo_id is None

    mock_client = AsyncMock()
    mock_coll = MagicMock()
    mock_coll.name = "repo_nandhini9074_create_demo10_transaction"
    mock_collections_resp = MagicMock()
    mock_collections_resp.collections = [mock_coll]
    mock_client.get_collections.return_value = mock_collections_resp

    with patch(
        "app.modules.search.pipeline.collection_selection.get_qdrant_client",
        return_value=mock_client,
    ):
        await stage.execute(context)

    assert context.early_exit is None
    assert context.qdrant_collection == "repo_nandhini9074_create_demo10_transaction"
    assert context.repo_owner == "nandhini9074"
    assert context.repo_name == "create_demo10_transaction"
    assert context.repo_id is None


@pytest.mark.asyncio
async def test_stage_local_repo_format_selection():
    """Verify CollectionSelectionStage resolves repo_local_repositoryname."""
    stage = CollectionSelectionStage()
    context = SearchContext(
        repo_name="demo10_transaction",
        query="test query",
    )

    mock_client = AsyncMock()
    mock_coll = MagicMock()
    mock_coll.name = "repo_local_demo10_transaction"
    mock_collections_resp = MagicMock()
    mock_collections_resp.collections = [mock_coll]
    mock_client.get_collections.return_value = mock_collections_resp

    with patch(
        "app.modules.search.pipeline.collection_selection.get_qdrant_client",
        return_value=mock_client,
    ):
        await stage.execute(context)

    assert context.early_exit is None
    assert context.qdrant_collection == "repo_local_demo10_transaction"
    assert context.repo_owner is None
    assert context.repo_name == "demo10_transaction"


@pytest.mark.asyncio
async def test_stage_repository_not_found():
    """Verify CollectionSelectionStage triggers EARLY_EXIT_A when collection does not match."""
    stage = CollectionSelectionStage()
    context = SearchContext(
        repo_name="unknown_repository",
        query="test query",
    )

    mock_client = AsyncMock()
    mock_collections_resp = MagicMock()
    mock_collections_resp.collections = []
    mock_client.get_collections.return_value = mock_collections_resp

    with patch(
        "app.modules.search.pipeline.collection_selection.get_qdrant_client",
        return_value=mock_client,
    ):
        await stage.execute(context)

    assert context.early_exit == "EARLY_EXIT_A"
    assert "could not be found" in context.early_exit_message
    assert context.qdrant_collection is None
