"""
tests/unit/test_webhook_validator.py
Tests for WebhookValidator.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core.exceptions import ValidationError
from app.modules.webhooks.validators.webhook_validator import WebhookValidator


@pytest.fixture
def mock_repo_repo():
    return AsyncMock()


@pytest.fixture
def validator(mock_repo_repo):
    return WebhookValidator(mock_repo_repo)


@pytest.mark.asyncio
async def test_validate_push_event_valid(validator, mock_repo_repo):
    """Test valid push event."""
    payload = {
        "ref": "refs/heads/main",
        "repository": {"full_name": "test/repo"}
    }
    
    mock_repo = MagicMock()
    mock_repo.default_branch = "main"
    mock_repo_repo.get_by_full_name.return_value = mock_repo
    
    result = await validator.validate_push_event("push", payload)
    
    assert result["repo"] == mock_repo
    assert result["branch"] == "main"
    mock_repo_repo.get_by_full_name.assert_called_once_with("test/repo")


@pytest.mark.asyncio
async def test_validate_push_event_invalid_type(validator):
    """Test invalid event type."""
    with pytest.raises(ValidationError, match="Unsupported event type"):
        await validator.validate_push_event("pull_request", {})


@pytest.mark.asyncio
async def test_validate_push_event_not_branch(validator):
    """Test push that is not to a branch (e.g. tag)."""
    payload = {"ref": "refs/tags/v1.0.0"}
    
    with pytest.raises(ValidationError, match="Not a push to a branch"):
        await validator.validate_push_event("push", payload)


@pytest.mark.asyncio
async def test_validate_push_event_missing_name(validator):
    """Test payload missing full_name."""
    payload = {
        "ref": "refs/heads/main",
        "repository": {}
    }
    
    with pytest.raises(ValidationError, match="Repository full_name not found in payload"):
        await validator.validate_push_event("push", payload)


@pytest.mark.asyncio
async def test_validate_push_event_repo_not_found(validator, mock_repo_repo):
    """Test when repo is not in DB."""
    payload = {
        "ref": "refs/heads/main",
        "repository": {"full_name": "test/repo"}
    }
    
    mock_repo_repo.get_by_full_name.return_value = None
    
    with pytest.raises(ValidationError, match="Repository test/repo not registered"):
        await validator.validate_push_event("push", payload)


@pytest.mark.asyncio
async def test_validate_push_event_wrong_branch(validator, mock_repo_repo):
    """Test when push is to a non-default branch."""
    payload = {
        "ref": "refs/heads/feature",
        "repository": {"full_name": "test/repo"}
    }
    
    mock_repo = MagicMock()
    mock_repo.default_branch = "main"
    mock_repo_repo.get_by_full_name.return_value = mock_repo
    
    with pytest.raises(ValidationError, match="not registered or not default branch"):
        await validator.validate_push_event("push", payload)
