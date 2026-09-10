"""
app/infrastructure/github/hooks_client.py
Async client for the GitHub Repository Hooks API.

Supports:
- Listing existing webhooks (used for idempotency check)
- Creating a repository webhook
- Deleting a repository webhook

All methods accept a per-repo GitHub token.
Secrets are NEVER logged.
"""

from __future__ import annotations

import json as _json
from typing import Any

from app.core.exceptions import GitHubWebhookError
from app.core.logging import get_logger
from app.infrastructure.github.github_client import get_github_client

logger = get_logger(__name__)

# The events we subscribe to
_WEBHOOK_EVENTS = ["push"]


async def list_webhooks(
    owner: str,
    repo: str,
    github_token: str,
) -> list[dict[str, Any]]:
    """
    List all webhooks configured on a GitHub repository.

    Args:
        owner: Repository owner (GitHub username or org).
        repo: Repository slug.
        github_token: PAT with admin:repo_hook (or Webhooks read) permission.

    Returns:
        List of webhook config dicts from GitHub.

    Raises:
        GitHubWebhookError: On GitHub API error.
    """
    client = get_github_client()
    endpoint = f"/repos/{owner}/{repo}/hooks"
    logger.debug("github_list_webhooks_started", owner=owner, repo=repo)

    try:
        response = await client.request("GET", endpoint, github_token=github_token)
        return response.json()  # type: ignore[return-value]
    except Exception as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        _raise_webhook_error(
            exc,
            status_code=status_code,
            endpoint=endpoint,
            action="list webhooks",
            owner=owner,
            repo=repo,
        )


async def create_webhook(
    owner: str,
    repo: str,
    payload_url: str,
    secret: str,
    github_token: str,
) -> int:
    """
    Create a push webhook on a GitHub repository, or return an existing one
    with the same payload URL (idempotent).

    Args:
        owner: Repository owner.
        repo: Repository slug.
        payload_url: The public URL GitHub will POST push events to.
        secret: HMAC secret used by GitHub to sign requests.
                NEVER logged.
        github_token: PAT with admin:repo_hook permission. NEVER logged.

    Returns:
        The webhook ID (integer) — new or reused.

    Raises:
        GitHubWebhookError: If GitHub rejects the request.
    """
    # --- Idempotency check: reuse existing hook with same payload URL ---
    try:
        existing = await list_webhooks(owner, repo, github_token)
        for hook in existing:
            hook_url = hook.get("config", {}).get("url", "")
            if hook_url == payload_url:
                hook_id: int = hook["id"]
                logger.info(
                    "github_webhook_already_exists",
                    owner=owner,
                    repo=repo,
                    webhook_id=hook_id,
                )
                return hook_id
    except GitHubWebhookError:
        # If listing fails, proceed to attempt creation and let that failure surface
        logger.warning(
            "github_list_webhooks_failed_proceeding_to_create",
            owner=owner,
            repo=repo,
        )

    # --- Create new webhook ---
    client = get_github_client()
    endpoint = f"/repos/{owner}/{repo}/hooks"

    # Build body WITHOUT logging it (contains secret)
    body = {
        "name": "web",
        "active": True,
        "events": _WEBHOOK_EVENTS,
        "config": {
            "url": payload_url,
            "content_type": "json",
            "secret": secret,
            "insecure_ssl": "0",
        },
    }

    logger.info(
        "github_webhook_creation_started",
        owner=owner,
        repo=repo,
        payload_url=payload_url,
        events=_WEBHOOK_EVENTS,
    )

    try:
        response = await client.request(
            "POST",
            endpoint,
            github_token=github_token,
            content=_json.dumps(body),
            headers={"Content-Type": "application/json"},
        )
        data: dict[str, Any] = response.json()
        webhook_id: int = data["id"]
        logger.info(
            "github_webhook_created",
            owner=owner,
            repo=repo,
            webhook_id=webhook_id,
            payload_url=payload_url,
        )
        return webhook_id
    except Exception as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        _raise_webhook_error(
            exc,
            status_code=status_code,
            endpoint=endpoint,
            action="create webhook",
            owner=owner,
            repo=repo,
        )


async def delete_webhook(
    owner: str,
    repo: str,
    webhook_id: int,
    github_token: str,
) -> bool:
    """
    Delete a webhook from a GitHub repository.

    A 404 response is treated as "already deleted" and returns True.

    Args:
        owner: Repository owner.
        repo: Repository slug.
        webhook_id: The GitHub webhook ID to delete.
        github_token: PAT with admin:repo_hook permission. NEVER logged.

    Returns:
        True if the webhook is gone (deleted or was already absent).

    Raises:
        GitHubWebhookError: On 401/403 or unexpected server errors.
    """
    client = get_github_client()
    endpoint = f"/repos/{owner}/{repo}/hooks/{webhook_id}"

    logger.info(
        "github_webhook_deletion_started",
        owner=owner,
        repo=repo,
        webhook_id=webhook_id,
    )

    try:
        await client.request("DELETE", endpoint, github_token=github_token)
        logger.info(
            "github_webhook_deleted",
            owner=owner,
            repo=repo,
            webhook_id=webhook_id,
        )
        return True
    except Exception as exc:
        from app.core.exceptions import GitHubNotFoundError

        # 404 = already gone — treat as success
        if isinstance(exc, GitHubNotFoundError):
            logger.info(
                "github_webhook_not_found",
                owner=owner,
                repo=repo,
                webhook_id=webhook_id,
                reason="Webhook was already deleted or never existed",
            )
            return True

        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        _raise_webhook_error(
            exc,
            status_code=status_code,
            endpoint=endpoint,
            action="delete webhook",
            owner=owner,
            repo=repo,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _raise_webhook_error(
    exc: Exception,
    *,
    status_code: int | None,
    endpoint: str,
    action: str,
    owner: str,
    repo: str,
) -> None:
    """
    Convert any GitHub client exception into a GitHubWebhookError.
    Never re-raises the raw exception to avoid leaking sensitive context.
    Logs a safe summary without PAT or secrets.
    """
    if status_code is None:
        if hasattr(exc, "details") and isinstance(exc.details, dict):
            status_code = exc.details.get("github_status_code")
        if status_code is None and hasattr(exc, "status_code"):
            status_code = getattr(exc, "status_code")

    logger.error(
        "github_webhook_action_failed",
        action=action,
        owner=owner,
        repo=repo,
        status_code=status_code,
    )
    raise GitHubWebhookError(
        f"GitHub Hooks API error during '{action}': {exc}",
        status_code=status_code,
        endpoint=endpoint,
    ) from exc

