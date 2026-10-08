"""
tests/unit/test_hooks_client.py
Unit tests for app/infrastructure/github/hooks_client.py.

Mocks GitHubClient so no real network calls are made.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.exceptions import GitHubNotFoundError, GitHubWebhookError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(status_code: int, json_data=None, raise_for_status=False):
    """Build a mock httpx.Response-like object."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    if raise_for_status:
        from httpx import HTTPStatusError, Request, Response
        resp.raise_for_status.side_effect = HTTPStatusError(
            "error", request=MagicMock(), response=MagicMock(status_code=status_code)
        )
    return resp


OWNER = "test-owner"
REPO = "test-repo"
PAYLOAD_URL = "https://example.ngrok.io/api/v1/webhooks/github"
SECRET = "super-secret"
TOKEN = "ghp_testtoken"
WEBHOOK_ID = 42


# ---------------------------------------------------------------------------
# list_webhooks
# ---------------------------------------------------------------------------

class TestListWebhooks:
    @pytest.mark.asyncio
    async def test_returns_list_on_success(self):
        hooks = [{"id": 1, "config": {"url": PAYLOAD_URL}}]
        mock_client = AsyncMock()
        mock_client.request.return_value = _make_response(200, json_data=hooks)

        with patch("app.infrastructure.github.hooks_client.get_github_client", return_value=mock_client):
            from app.infrastructure.github.hooks_client import list_webhooks
            result = await list_webhooks(OWNER, REPO, TOKEN)

        assert result == hooks
        mock_client.request.assert_called_once_with("GET", f"/repos/{OWNER}/{REPO}/hooks", github_token=TOKEN)

    @pytest.mark.asyncio
    async def test_raises_webhook_error_on_github_error(self):
        from app.core.exceptions import GitHubAPIError
        mock_client = AsyncMock()
        mock_client.request.side_effect = GitHubAPIError("403 Forbidden", status_code=403)

        with patch("app.infrastructure.github.hooks_client.get_github_client", return_value=mock_client):
            from app.infrastructure.github.hooks_client import list_webhooks
            with pytest.raises(GitHubWebhookError):
                await list_webhooks(OWNER, REPO, TOKEN)


# ---------------------------------------------------------------------------
# create_webhook
# ---------------------------------------------------------------------------

class TestCreateWebhook:
    @pytest.mark.asyncio
    async def test_creates_new_webhook_when_none_exists(self):
        """create_webhook returns new ID when no existing hook matches payload_url."""
        mock_client = AsyncMock()
        # list_webhooks → empty list
        # create → returns new hook
        mock_client.request.side_effect = [
            _make_response(200, json_data=[]),                          # GET /hooks
            _make_response(201, json_data={"id": WEBHOOK_ID}),          # POST /hooks
        ]

        with patch("app.infrastructure.github.hooks_client.get_github_client", return_value=mock_client):
            from app.infrastructure.github.hooks_client import create_webhook
            result = await create_webhook(OWNER, REPO, PAYLOAD_URL, SECRET, TOKEN)

        assert result == WEBHOOK_ID

    @pytest.mark.asyncio
    async def test_reuses_existing_webhook_with_same_url(self):
        """Idempotency: returns existing hook ID instead of creating a new one."""
        existing_id = 99
        mock_client = AsyncMock()
        mock_client.request.return_value = _make_response(
            200,
            json_data=[{"id": existing_id, "config": {"url": PAYLOAD_URL}}],
        )

        with patch("app.infrastructure.github.hooks_client.get_github_client", return_value=mock_client):
            from app.infrastructure.github.hooks_client import create_webhook
            result = await create_webhook(OWNER, REPO, PAYLOAD_URL, SECRET, TOKEN)

        assert result == existing_id
        # Only the GET call should have been made — no POST
        assert mock_client.request.call_count == 1

    @pytest.mark.asyncio
    async def test_does_not_reuse_hook_with_different_url(self):
        """Hook with different URL is not reused — creates a new one."""
        mock_client = AsyncMock()
        mock_client.request.side_effect = [
            _make_response(200, json_data=[{"id": 5, "config": {"url": "https://other.example.com/webhook"}}]),
            _make_response(201, json_data={"id": WEBHOOK_ID}),
        ]

        with patch("app.infrastructure.github.hooks_client.get_github_client", return_value=mock_client):
            from app.infrastructure.github.hooks_client import create_webhook
            result = await create_webhook(OWNER, REPO, PAYLOAD_URL, SECRET, TOKEN)

        assert result == WEBHOOK_ID
        assert mock_client.request.call_count == 2

    @pytest.mark.asyncio
    async def test_sends_push_event_only(self):
        """Webhook must only subscribe to 'push' events."""
        import json
        mock_client = AsyncMock()
        mock_client.request.side_effect = [
            _make_response(200, json_data=[]),
            _make_response(201, json_data={"id": WEBHOOK_ID}),
        ]

        with patch("app.infrastructure.github.hooks_client.get_github_client", return_value=mock_client):
            from app.infrastructure.github.hooks_client import create_webhook
            await create_webhook(OWNER, REPO, PAYLOAD_URL, SECRET, TOKEN)

        post_call = mock_client.request.call_args_list[1]
        body = json.loads(post_call.kwargs["content"])
        assert body["events"] == ["push"]
        assert body["config"]["content_type"] == "json"
        assert body["config"]["url"] == PAYLOAD_URL

    @pytest.mark.asyncio
    async def test_raises_webhook_error_on_403(self):
        """403 → GitHubWebhookError with safe_reason."""
        from app.core.exceptions import GitHubAPIError
        mock_client = AsyncMock()
        mock_client.request.side_effect = [
            _make_response(200, json_data=[]),
            GitHubAPIError("Forbidden", status_code=403),
        ]

        with patch("app.infrastructure.github.hooks_client.get_github_client", return_value=mock_client):
            from app.infrastructure.github.hooks_client import create_webhook
            with pytest.raises(GitHubWebhookError) as exc_info:
                await create_webhook(OWNER, REPO, PAYLOAD_URL, SECRET, TOKEN)

        assert exc_info.value.details.get("github_status_code") == 403

    @pytest.mark.asyncio
    async def test_raises_webhook_error_on_401(self):
        from app.core.exceptions import GitHubAPIError
        mock_client = AsyncMock()
        mock_client.request.side_effect = [
            _make_response(200, json_data=[]),
            GitHubAPIError("Unauthorized", status_code=401),
        ]

        with patch("app.infrastructure.github.hooks_client.get_github_client", return_value=mock_client):
            from app.infrastructure.github.hooks_client import create_webhook
            with pytest.raises(GitHubWebhookError) as exc_info:
                await create_webhook(OWNER, REPO, PAYLOAD_URL, SECRET, TOKEN)

        assert exc_info.value.details.get("github_status_code") == 401

    @pytest.mark.asyncio
    async def test_raises_webhook_error_on_404(self):
        mock_client = AsyncMock()
        mock_client.request.side_effect = [
            _make_response(200, json_data=[]),
            GitHubNotFoundError("Not Found", status_code=404),
        ]

        with patch("app.infrastructure.github.hooks_client.get_github_client", return_value=mock_client):
            from app.infrastructure.github.hooks_client import create_webhook
            with pytest.raises(GitHubWebhookError) as exc_info:
                await create_webhook(OWNER, REPO, PAYLOAD_URL, SECRET, TOKEN)

        assert exc_info.value.details.get("github_status_code") == 404

    @pytest.mark.asyncio
    async def test_secret_not_in_log(self, caplog):
        """Webhook secret must never appear in logs."""
        import logging
        mock_client = AsyncMock()
        mock_client.request.side_effect = [
            _make_response(200, json_data=[]),
            _make_response(201, json_data={"id": WEBHOOK_ID}),
        ]

        with patch("app.infrastructure.github.hooks_client.get_github_client", return_value=mock_client):
            from app.infrastructure.github.hooks_client import create_webhook
            with caplog.at_level(logging.DEBUG):
                await create_webhook(OWNER, REPO, PAYLOAD_URL, SECRET, TOKEN)

        for record in caplog.records:
            assert SECRET not in record.getMessage()
            assert TOKEN not in record.getMessage()


# ---------------------------------------------------------------------------
# delete_webhook
# ---------------------------------------------------------------------------

class TestDeleteWebhook:
    @pytest.mark.asyncio
    async def test_returns_true_on_204(self):
        mock_client = AsyncMock()
        mock_client.request.return_value = _make_response(204)

        with patch("app.infrastructure.github.hooks_client.get_github_client", return_value=mock_client):
            from app.infrastructure.github.hooks_client import delete_webhook
            result = await delete_webhook(OWNER, REPO, WEBHOOK_ID, TOKEN)

        assert result is True
        mock_client.request.assert_called_once_with(
            "DELETE", f"/repos/{OWNER}/{REPO}/hooks/{WEBHOOK_ID}", github_token=TOKEN
        )

    @pytest.mark.asyncio
    async def test_returns_true_on_404(self):
        """404 means hook already gone — treat as success."""
        mock_client = AsyncMock()
        mock_client.request.side_effect = GitHubNotFoundError("Not Found", status_code=404)

        with patch("app.infrastructure.github.hooks_client.get_github_client", return_value=mock_client):
            from app.infrastructure.github.hooks_client import delete_webhook
            result = await delete_webhook(OWNER, REPO, WEBHOOK_ID, TOKEN)

        assert result is True

    @pytest.mark.asyncio
    async def test_raises_on_403(self):
        from app.core.exceptions import GitHubAPIError
        mock_client = AsyncMock()
        mock_client.request.side_effect = GitHubAPIError("Forbidden", status_code=403)

        with patch("app.infrastructure.github.hooks_client.get_github_client", return_value=mock_client):
            from app.infrastructure.github.hooks_client import delete_webhook
            with pytest.raises(GitHubWebhookError):
                await delete_webhook(OWNER, REPO, WEBHOOK_ID, TOKEN)
