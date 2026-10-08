"""
tests/unit/test_repository_service_webhook.py
Unit tests for GitHub webhook integration in RepositoryService.

Tests registration flow (webhook creation), deletion flow (webhook cleanup),
idempotency, failure cases, and security (no PAT/secret leakage).
"""

from __future__ import annotations

import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch, call


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

OWNER = "test-owner"
REPO_NAME = "test-repo"
REPO_URL = f"https://github.com/{OWNER}/{REPO_NAME}"
PAT = "ghp_testtokenvalue"
WEBHOOK_SECRET = "test-webhook-secret"
BASE_URL = "https://example.ngrok.io"
PAYLOAD_URL = f"{BASE_URL}/api/v1/webhooks/github"
WEBHOOK_ID = 77
REPO_ID = str(uuid.uuid4())


from app.infrastructure.database.models.repository import Repository


def _make_mock_repo(webhook_id=None, token=PAT):
    return Repository(
        id=uuid.UUID(REPO_ID),
        repo_name=REPO_NAME,
        repo_url=REPO_URL,
        source_type="github",
        default_branch="main",
        is_private=False,
        access_token_ref=token,
        qdrant_collection_name=f"repo_{OWNER}_{REPO_NAME}",
        last_indexed_commit_sha="abcdef1234567890",
        github_webhook_id=webhook_id,
    )


def _make_service(mock_repo_repo, mock_job_repo=None):
    from app.modules.repositories.service.repository_service import RepositoryService
    return RepositoryService(mock_repo_repo, mock_job_repo)


# ---------------------------------------------------------------------------
# Registration: webhook creation
# ---------------------------------------------------------------------------

class TestRegistrationWebhookCreation:

    @pytest.mark.asyncio
    async def test_registration_with_pat_creates_webhook(self):
        """Successful registration with PAT → webhook created, webhook_configured=True."""
        mock_repo_repo = AsyncMock()
        mock_repo_repo.get_by_url.return_value = None
        mock_repo_repo.get_by_full_name.return_value = None
        mock_repo_repo.create.return_value = _make_mock_repo(webhook_id=None)
        mock_repo_repo.update_fields = AsyncMock()

        with (
            patch("app.modules.repositories.service.repository_service.validate_and_parse_github_url", return_value=(OWNER, REPO_NAME)),
            patch("app.modules.repositories.service.repository_service.get_settings") as mock_settings,
            patch("app.infrastructure.github.hooks_client.get_github_client") as mock_get_client,
            patch("app.infrastructure.qdrant.collection_manager.ensure_collection_exists", new_callable=AsyncMock),
        ):
            settings = MagicMock()
            settings.github_webhook_secret = WEBHOOK_SECRET
            settings.app_base_url = BASE_URL
            settings.webhook_payload_url = PAYLOAD_URL
            mock_settings.return_value = settings

            mock_client = AsyncMock()
            mock_client.request.side_effect = [
                MagicMock(json=lambda: [], status_code=200),   # list_webhooks
                MagicMock(json=lambda: {"id": WEBHOOK_ID}, status_code=201),  # create
            ]
            mock_get_client.return_value = mock_client

            from app.modules.repositories.service.repository_service import RepositoryService
            from app.modules.repositories.schemas.repository_schema import CreateRepositoryRequest
            service = RepositoryService(mock_repo_repo, job_repo=None)
            request = CreateRepositoryRequest(repo_url=REPO_URL, pat_token=PAT)

            response = await service.register_repository_with_response(request)

        assert response.webhook_configured is True
        assert response.webhook_error is None
        mock_repo_repo.update_fields.assert_called_once()
        call_args = mock_repo_repo.update_fields.call_args
        assert call_args[0][1].get("github_webhook_id") == WEBHOOK_ID

    @pytest.mark.asyncio
    async def test_registration_without_pat_skips_webhook(self):
        """No PAT → webhook_configured=False, safe message returned."""
        mock_repo_repo = AsyncMock()
        mock_repo_repo.get_by_url.return_value = None
        mock_repo_repo.get_by_full_name.return_value = None
        mock_repo_repo.create.return_value = _make_mock_repo(webhook_id=None, token=None)

        with (
            patch("app.modules.repositories.service.repository_service.validate_and_parse_github_url", return_value=(OWNER, REPO_NAME)),
            patch("app.modules.repositories.service.repository_service.get_settings") as mock_settings,
            patch("app.infrastructure.qdrant.collection_manager.ensure_collection_exists", new_callable=AsyncMock),
        ):
            settings = MagicMock()
            settings.github_webhook_secret = WEBHOOK_SECRET
            settings.app_base_url = BASE_URL
            settings.webhook_payload_url = PAYLOAD_URL
            mock_settings.return_value = settings

            from app.modules.repositories.service.repository_service import RepositoryService
            from app.modules.repositories.schemas.repository_schema import CreateRepositoryRequest
            service = RepositoryService(mock_repo_repo, job_repo=None)
            request = CreateRepositoryRequest(repo_url=REPO_URL, pat_token=None)

            response = await service.register_repository_with_response(request)

        assert response.webhook_configured is False
        assert "No GitHub token" in (response.webhook_error or "")

    @pytest.mark.asyncio
    async def test_registration_github_403_webhook_configured_false(self):
        """GitHub 403 → repo saved, webhook_configured=False, safe error in response."""
        from app.core.exceptions import GitHubAPIError
        mock_repo_repo = AsyncMock()
        mock_repo_repo.get_by_url.return_value = None
        mock_repo_repo.get_by_full_name.return_value = None
        mock_repo_repo.create.return_value = _make_mock_repo()

        with (
            patch("app.modules.repositories.service.repository_service.validate_and_parse_github_url", return_value=(OWNER, REPO_NAME)),
            patch("app.modules.repositories.service.repository_service.get_settings") as mock_settings,
            patch("app.infrastructure.github.hooks_client.get_github_client") as mock_get_client,
            patch("app.infrastructure.qdrant.collection_manager.ensure_collection_exists", new_callable=AsyncMock),
        ):
            settings = MagicMock()
            settings.github_webhook_secret = WEBHOOK_SECRET
            settings.app_base_url = BASE_URL
            settings.webhook_payload_url = PAYLOAD_URL
            mock_settings.return_value = settings

            mock_client = AsyncMock()
            mock_client.request.side_effect = [
                MagicMock(json=lambda: [], status_code=200),
                GitHubAPIError("Forbidden", status_code=403),
            ]
            mock_get_client.return_value = mock_client

            from app.modules.repositories.service.repository_service import RepositoryService
            from app.modules.repositories.schemas.repository_schema import CreateRepositoryRequest
            service = RepositoryService(mock_repo_repo, job_repo=None)
            request = CreateRepositoryRequest(repo_url=REPO_URL, pat_token=PAT)

            response = await service.register_repository_with_response(request)

        # Repo is still registered
        mock_repo_repo.create.assert_called_once()
        # But webhook failed
        assert response.webhook_configured is False
        assert response.webhook_error is not None
        # Safe message — no PAT, no secret
        assert PAT not in (response.webhook_error or "")
        assert WEBHOOK_SECRET not in (response.webhook_error or "")

    @pytest.mark.asyncio
    async def test_registration_github_401_webhook_configured_false(self):
        """GitHub 401 → repo saved, webhook_configured=False."""
        from app.core.exceptions import GitHubAPIError
        mock_repo_repo = AsyncMock()
        mock_repo_repo.get_by_url.return_value = None
        mock_repo_repo.get_by_full_name.return_value = None
        mock_repo_repo.create.return_value = _make_mock_repo()

        with (
            patch("app.modules.repositories.service.repository_service.validate_and_parse_github_url", return_value=(OWNER, REPO_NAME)),
            patch("app.modules.repositories.service.repository_service.get_settings") as mock_settings,
            patch("app.infrastructure.github.hooks_client.get_github_client") as mock_get_client,
            patch("app.infrastructure.qdrant.collection_manager.ensure_collection_exists", new_callable=AsyncMock),
        ):
            settings = MagicMock()
            settings.github_webhook_secret = WEBHOOK_SECRET
            settings.app_base_url = BASE_URL
            settings.webhook_payload_url = PAYLOAD_URL
            mock_settings.return_value = settings

            mock_client = AsyncMock()
            mock_client.request.side_effect = [
                MagicMock(json=lambda: [], status_code=200),
                GitHubAPIError("Unauthorized", status_code=401),
            ]
            mock_get_client.return_value = mock_client

            from app.modules.repositories.service.repository_service import RepositoryService
            from app.modules.repositories.schemas.repository_schema import CreateRepositoryRequest
            service = RepositoryService(mock_repo_repo, job_repo=None)
            request = CreateRepositoryRequest(repo_url=REPO_URL, pat_token=PAT)
            response = await service.register_repository_with_response(request)

        assert response.webhook_configured is False

    @pytest.mark.asyncio
    async def test_registration_localhost_base_url_skips_webhook(self):
        """APP_BASE_URL=localhost → webhook skipped with clear message."""
        mock_repo_repo = AsyncMock()
        mock_repo_repo.get_by_url.return_value = None
        mock_repo_repo.get_by_full_name.return_value = None
        mock_repo_repo.create.return_value = _make_mock_repo()

        with (
            patch("app.modules.repositories.service.repository_service.validate_and_parse_github_url", return_value=(OWNER, REPO_NAME)),
            patch("app.modules.repositories.service.repository_service.get_settings") as mock_settings,
            patch("app.infrastructure.qdrant.collection_manager.ensure_collection_exists", new_callable=AsyncMock),
        ):
            settings = MagicMock()
            settings.github_webhook_secret = WEBHOOK_SECRET
            settings.app_base_url = "http://localhost:8000"
            settings.webhook_payload_url = "http://localhost:8000/api/v1/webhooks/github"
            mock_settings.return_value = settings

            from app.modules.repositories.service.repository_service import RepositoryService
            from app.modules.repositories.schemas.repository_schema import CreateRepositoryRequest
            service = RepositoryService(mock_repo_repo, job_repo=None)
            request = CreateRepositoryRequest(repo_url=REPO_URL, pat_token=PAT)
            response = await service.register_repository_with_response(request)

        assert response.webhook_configured is False
        assert "localhost" in (response.webhook_error or "").lower()

    @pytest.mark.asyncio
    async def test_webhook_payload_url_correct_format(self):
        """Payload URL must be exactly {BASE_URL}/api/v1/webhooks/github."""
        import json as _json
        mock_repo_repo = AsyncMock()
        mock_repo_repo.get_by_url.return_value = None
        mock_repo_repo.get_by_full_name.return_value = None
        mock_repo_repo.create.return_value = _make_mock_repo()
        mock_repo_repo.update_fields = AsyncMock()

        captured_body = {}

        async def fake_request(method, endpoint, **kwargs):
            if method == "GET":
                resp = MagicMock()
                resp.json.return_value = []
                return resp
            elif method == "POST":
                captured_body.update(_json.loads(kwargs.get("content", "{}")))
                resp = MagicMock()
                resp.json.return_value = {"id": WEBHOOK_ID}
                return resp

        with (
            patch("app.modules.repositories.service.repository_service.validate_and_parse_github_url", return_value=(OWNER, REPO_NAME)),
            patch("app.modules.repositories.service.repository_service.get_settings") as mock_settings,
            patch("app.infrastructure.github.hooks_client.get_github_client") as mock_get_client,
            patch("app.infrastructure.qdrant.collection_manager.ensure_collection_exists", new_callable=AsyncMock),
        ):
            settings = MagicMock()
            settings.github_webhook_secret = WEBHOOK_SECRET
            settings.app_base_url = BASE_URL
            settings.webhook_payload_url = PAYLOAD_URL
            mock_settings.return_value = settings

            mock_client = MagicMock()
            mock_client.request = AsyncMock(side_effect=fake_request)
            mock_get_client.return_value = mock_client

            from app.modules.repositories.service.repository_service import RepositoryService
            from app.modules.repositories.schemas.repository_schema import CreateRepositoryRequest
            service = RepositoryService(mock_repo_repo, job_repo=None)
            request = CreateRepositoryRequest(repo_url=REPO_URL, pat_token=PAT)
            await service.register_repository_with_response(request)

        assert captured_body.get("config", {}).get("url") == PAYLOAD_URL
        assert captured_body.get("events") == ["push"]
        assert captured_body.get("config", {}).get("content_type") == "json"

    @pytest.mark.asyncio
    async def test_webhook_secret_not_in_response(self):
        """API response must never contain the webhook secret."""
        mock_repo_repo = AsyncMock()
        mock_repo_repo.get_by_url.return_value = None
        mock_repo_repo.get_by_full_name.return_value = None
        mock_repo_repo.create.return_value = _make_mock_repo()
        mock_repo_repo.update_fields = AsyncMock()

        with (
            patch("app.modules.repositories.service.repository_service.validate_and_parse_github_url", return_value=(OWNER, REPO_NAME)),
            patch("app.modules.repositories.service.repository_service.get_settings") as mock_settings,
            patch("app.infrastructure.github.hooks_client.get_github_client") as mock_get_client,
            patch("app.infrastructure.qdrant.collection_manager.ensure_collection_exists", new_callable=AsyncMock),
        ):
            settings = MagicMock()
            settings.github_webhook_secret = WEBHOOK_SECRET
            settings.app_base_url = BASE_URL
            settings.webhook_payload_url = PAYLOAD_URL
            mock_settings.return_value = settings

            mock_client = AsyncMock()
            mock_client.request.side_effect = [
                MagicMock(json=lambda: [], status_code=200),
                MagicMock(json=lambda: {"id": WEBHOOK_ID}, status_code=201),
            ]
            mock_get_client.return_value = mock_client

            from app.modules.repositories.service.repository_service import RepositoryService
            from app.modules.repositories.schemas.repository_schema import CreateRepositoryRequest
            service = RepositoryService(mock_repo_repo, job_repo=None)
            request = CreateRepositoryRequest(repo_url=REPO_URL, pat_token=PAT)
            response = await service.register_repository_with_response(request)

        response_json = response.model_dump_json()
        assert WEBHOOK_SECRET not in response_json
        assert PAT not in response_json

    @pytest.mark.asyncio
    async def test_no_webhook_secret_configured_skips_webhook(self):
        """GITHUB_WEBHOOK_SECRET not set → webhook skipped safely."""
        mock_repo_repo = AsyncMock()
        mock_repo_repo.get_by_url.return_value = None
        mock_repo_repo.get_by_full_name.return_value = None
        mock_repo_repo.create.return_value = _make_mock_repo()

        with (
            patch("app.modules.repositories.service.repository_service.validate_and_parse_github_url", return_value=(OWNER, REPO_NAME)),
            patch("app.modules.repositories.service.repository_service.get_settings") as mock_settings,
            patch("app.infrastructure.qdrant.collection_manager.ensure_collection_exists", new_callable=AsyncMock),
        ):
            settings = MagicMock()
            settings.github_webhook_secret = None  # not configured
            settings.app_base_url = BASE_URL
            settings.webhook_payload_url = PAYLOAD_URL
            mock_settings.return_value = settings

            from app.modules.repositories.service.repository_service import RepositoryService
            from app.modules.repositories.schemas.repository_schema import CreateRepositoryRequest
            service = RepositoryService(mock_repo_repo, job_repo=None)
            request = CreateRepositoryRequest(repo_url=REPO_URL, pat_token=PAT)
            response = await service.register_repository_with_response(request)

        assert response.webhook_configured is False
        assert "secret" in (response.webhook_error or "").lower()


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:

    @pytest.mark.asyncio
    async def test_existing_webhook_reused_not_duplicated(self):
        """If list_webhooks returns existing hook with same URL, no POST is made."""
        mock_repo_repo = AsyncMock()
        mock_repo_repo.get_by_url.return_value = None
        mock_repo_repo.get_by_full_name.return_value = None
        mock_repo_repo.create.return_value = _make_mock_repo()
        mock_repo_repo.update_fields = AsyncMock()

        existing_id = 55

        with (
            patch("app.modules.repositories.service.repository_service.validate_and_parse_github_url", return_value=(OWNER, REPO_NAME)),
            patch("app.modules.repositories.service.repository_service.get_settings") as mock_settings,
            patch("app.infrastructure.github.hooks_client.get_github_client") as mock_get_client,
            patch("app.infrastructure.qdrant.collection_manager.ensure_collection_exists", new_callable=AsyncMock),
        ):
            settings = MagicMock()
            settings.github_webhook_secret = WEBHOOK_SECRET
            settings.app_base_url = BASE_URL
            settings.webhook_payload_url = PAYLOAD_URL
            mock_settings.return_value = settings

            mock_client = AsyncMock()
            # list_webhooks returns hook with same URL → no POST
            mock_client.request.return_value = MagicMock(
                json=lambda: [{"id": existing_id, "config": {"url": PAYLOAD_URL}}],
                status_code=200,
            )
            mock_get_client.return_value = mock_client

            from app.modules.repositories.service.repository_service import RepositoryService
            from app.modules.repositories.schemas.repository_schema import CreateRepositoryRequest
            service = RepositoryService(mock_repo_repo, job_repo=None)
            request = CreateRepositoryRequest(repo_url=REPO_URL, pat_token=PAT)
            response = await service.register_repository_with_response(request)

        assert response.webhook_configured is True
        # Only one request = GET (no POST)
        assert mock_client.request.call_count == 1
        # Stored the existing ID
        call_args = mock_repo_repo.update_fields.call_args
        assert call_args[0][1].get("github_webhook_id") == existing_id


# ---------------------------------------------------------------------------
# Deletion flow
# ---------------------------------------------------------------------------

class TestDeletionWebhook:

    @pytest.mark.asyncio
    async def test_deletion_with_webhook_id_deletes_from_github(self):
        """Repo with github_webhook_id → DELETE call made to GitHub."""
        repo = _make_mock_repo(webhook_id=WEBHOOK_ID)
        mock_repo_repo = AsyncMock()
        mock_repo_repo.get_by_id.return_value = repo
        mock_repo_repo.delete = AsyncMock()

        with (
            patch("app.infrastructure.github.hooks_client.get_github_client") as mock_get_client,
            patch("app.infrastructure.qdrant.client.get_qdrant_client") as mock_qdrant,
        ):
            mock_client = AsyncMock()
            mock_client.request.return_value = MagicMock(status_code=204)
            mock_get_client.return_value = mock_client

            mock_qdrant.return_value = AsyncMock()

            from app.modules.repositories.service.repository_service import RepositoryService
            service = RepositoryService(mock_repo_repo, job_repo=None)
            await service.delete_repository(REPO_ID)

        mock_client.request.assert_called_once_with(
            "DELETE",
            f"/repos/{OWNER}/{REPO_NAME}/hooks/{WEBHOOK_ID}",
            github_token=PAT,
        )
        mock_repo_repo.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_deletion_github_404_continues_local_delete(self):
        """GitHub 404 on delete → local repo deletion still happens."""
        from app.core.exceptions import GitHubNotFoundError
        repo = _make_mock_repo(webhook_id=WEBHOOK_ID)
        mock_repo_repo = AsyncMock()
        mock_repo_repo.get_by_id.return_value = repo
        mock_repo_repo.delete = AsyncMock()

        with (
            patch("app.infrastructure.github.hooks_client.get_github_client") as mock_get_client,
            patch("app.infrastructure.qdrant.client.get_qdrant_client") as mock_qdrant,
        ):
            mock_client = AsyncMock()
            mock_client.request.side_effect = GitHubNotFoundError("Not Found", status_code=404)
            mock_get_client.return_value = mock_client
            mock_qdrant.return_value = AsyncMock()

            from app.modules.repositories.service.repository_service import RepositoryService
            service = RepositoryService(mock_repo_repo, job_repo=None)
            await service.delete_repository(REPO_ID)

        # Local deletion still happened
        mock_repo_repo.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_deletion_without_webhook_id_skips_github_call(self):
        """Repo without github_webhook_id → no GitHub DELETE call."""
        repo = _make_mock_repo(webhook_id=None)
        mock_repo_repo = AsyncMock()
        mock_repo_repo.get_by_id.return_value = repo
        mock_repo_repo.delete = AsyncMock()

        with (
            patch("app.infrastructure.github.hooks_client.get_github_client") as mock_get_client,
            patch("app.infrastructure.qdrant.client.get_qdrant_client") as mock_qdrant,
        ):
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client
            mock_qdrant.return_value = AsyncMock()

            from app.modules.repositories.service.repository_service import RepositoryService
            service = RepositoryService(mock_repo_repo, job_repo=None)
            await service.delete_repository(REPO_ID)

        mock_client.request.assert_not_called()
        mock_repo_repo.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_deletion_without_token_skips_github_call(self):
        """Repo without access_token_ref → no GitHub DELETE call."""
        repo = _make_mock_repo(webhook_id=WEBHOOK_ID, token=None)
        mock_repo_repo = AsyncMock()
        mock_repo_repo.get_by_id.return_value = repo
        mock_repo_repo.delete = AsyncMock()

        with (
            patch("app.infrastructure.github.hooks_client.get_github_client") as mock_get_client,
            patch("app.infrastructure.qdrant.client.get_qdrant_client") as mock_qdrant,
        ):
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client
            mock_qdrant.return_value = AsyncMock()

            from app.modules.repositories.service.repository_service import RepositoryService
            service = RepositoryService(mock_repo_repo, job_repo=None)
            await service.delete_repository(REPO_ID)

        mock_client.request.assert_not_called()
        mock_repo_repo.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_deletion_github_failure_still_deletes_locally(self):
        """GitHub 503 on delete → local deletion still proceeds."""
        from app.core.exceptions import GitHubAPIError
        repo = _make_mock_repo(webhook_id=WEBHOOK_ID)
        mock_repo_repo = AsyncMock()
        mock_repo_repo.get_by_id.return_value = repo
        mock_repo_repo.delete = AsyncMock()

        with (
            patch("app.infrastructure.github.hooks_client.get_github_client") as mock_get_client,
            patch("app.infrastructure.qdrant.client.get_qdrant_client") as mock_qdrant,
        ):
            mock_client = AsyncMock()
            mock_client.request.side_effect = GitHubAPIError("Server Error", status_code=503)
            mock_get_client.return_value = mock_client
            mock_qdrant.return_value = AsyncMock()

            from app.modules.repositories.service.repository_service import RepositoryService
            service = RepositoryService(mock_repo_repo, job_repo=None)
            await service.delete_repository(REPO_ID)

        mock_repo_repo.delete.assert_called_once()
