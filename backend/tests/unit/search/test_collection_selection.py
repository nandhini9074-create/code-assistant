"""Tests for source normalization and collection selection."""

from unittest.mock import AsyncMock, patch

import pytest

from app.modules.search.domain.search_domain import SearchContext
from app.modules.search.pipeline.collection_selection import (
    CollectionSelectionStage,
    normalize_source,
)


def test_normalize_github_url():
    collection, owner, repository = normalize_source(
        "git", "https://github.com/ashwathie/search_ambiguity_files"
    )
    assert collection == "repo_ashwathie_search_ambiguity_files"
    assert owner == "ashwathie"
    assert repository == "search_ambiguity_files"


def test_normalize_github_git_url():
    collection, owner, repository = normalize_source(
        "git", "https://github.com/ashwathie/search_ambiguity_files.git"
    )
    assert collection == "repo_ashwathie_search_ambiguity_files"
    assert owner == "ashwathie"
    assert repository == "search_ambiguity_files"


def test_normalize_zip_filename():
    collection, owner, repository = normalize_source(
        "zip", "search_ambiguity_files.zip"
    )
    assert collection == "repo_local_search_ambiguity_files"
    assert owner is None
    assert repository == "search_ambiguity_files"


@pytest.mark.parametrize(
    ("source_type", "location"),
    [
        ("svn", "https://example.com/repository"),
        ("git", "not-a-url"),
        ("git", "https://github.com/owner-only"),
        ("zip", "repository.tar.gz"),
        ("zip", ""),
    ],
)
def test_invalid_source_is_rejected(source_type: str, location: str):
    with pytest.raises(ValueError):
        normalize_source(source_type, location)


@pytest.mark.asyncio
async def test_stage_sets_source_fields_and_checks_only_resolved_collection():
    context = SearchContext(
        source_type="git",
        source_location="https://github.com/ashwathie/search_ambiguity_files",
        query="retrieve productservice function",
    )
    client = AsyncMock()

    with patch(
        "app.modules.search.pipeline.collection_selection.get_qdrant_client",
        return_value=client,
    ):
        await CollectionSelectionStage().execute(context)

    client.get_collection.assert_awaited_once_with(
        "repo_ashwathie_search_ambiguity_files"
    )
    assert context.repo_owner == "ashwathie"
    assert context.repo_name == "search_ambiguity_files"
    assert context.qdrant_collection == "repo_ashwathie_search_ambiguity_files"
    assert context.early_exit is None