"""
tests/unit/test_webhook_service.py
Tests for WebhookService event dispatch and handling.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.core.exceptions import ValidationError
from app.infrastructure.database.models.ingestion_job import IngestionJob
from app.modules.webhooks.schemas.webhook_schema import WebhookEventResponse
from app.modules.webhooks.service.webhook_service import WebhookService


@pytest.fixture
def mock_validator():
    return AsyncMock()


@pytest.fixture
def mock_job_repo():
    repo = AsyncMock()
    repo.create.return_value = IngestionJob(id="test-job-id")
    return repo


@pytest.fixture
def mock_event_repo():
    repo = AsyncMock()
    repo.exists.return_value = False
    return repo


@pytest.fixture
def service(mock_validator, mock_job_repo, mock_event_repo):
    return WebhookService(mock_validator, mock_job_repo, mock_event_repo)


@pytest.mark.asyncio
async def test_handle_event_ping(service, mock_event_repo):
    """Test handling of ping event."""
    payload = {"repository": {"full_name": "test/repo"}}
    response = await service.handle_event("ping", "delivery-123", payload)
    
    assert response.status == "ok"
    assert response.message == "pong"
    mock_event_repo.create.assert_called_once()
    event = mock_event_repo.create.call_args[0][0]
    assert event.event_type == "ping"
    assert event.delivery_id == "delivery-123"


@pytest.mark.asyncio
@patch("app.modules.webhooks.service.webhook_service.ingest_repository_task")
async def test_handle_event_push_valid(mock_task, service, mock_validator, mock_job_repo, mock_event_repo):
    """Test handling of valid push event."""
    payload = {
        "head_commit": {"id": "commit-123"},
        "commits": [
            {"added": ["file1.py"], "modified": [], "removed": []}
        ]
    }
    
    mock_repo = MagicMock()
    mock_repo.id = "repo-123"
    mock_validator.validate_push_event.return_value = {"repo": mock_repo, "branch": "main"}
    
    response = await service.handle_event("push", "delivery-123", payload)
    
    assert response.status == "accepted"
    assert response.job_id == "test-job-id"
    mock_job_repo.create.assert_called_once()
    mock_task.delay.assert_called_once()
    mock_event_repo.create.assert_called_once()
    event = mock_event_repo.create.call_args[0][0]
    assert event.event_type == "push"
    assert event.delivery_id == "delivery-123"


@pytest.mark.asyncio
async def test_handle_event_push_invalid_repo(service, mock_validator):
    """Test handling of push event for unregistered repo."""
    payload = {}
    mock_validator.validate_push_event.side_effect = ValidationError("Repo not found")
    
    response = await service.handle_event("push", "delivery-123", payload)
    
    assert response.status == "ignored"
    assert "Repo not found" in response.message


@pytest.mark.asyncio
async def test_handle_event_duplicate_delivery(service, mock_event_repo):
    """Test handling of duplicate delivery."""
    mock_event_repo.exists.return_value = True
    payload = {}
    
    response = await service.handle_event("push", "delivery-123", payload)
    
    assert response.status == "ignored"
    assert "Duplicate delivery" in response.message


@pytest.mark.asyncio
async def test_handle_event_unknown_type(service):
    """Test handling of unknown event type."""
    payload = {}
    
    response = await service.handle_event("pull_request", "delivery-123", payload)
    
    assert response.status == "ignored"
    assert "Unsupported event: pull_request" in response.message
