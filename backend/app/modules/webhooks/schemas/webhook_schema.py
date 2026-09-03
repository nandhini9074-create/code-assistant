"""
app/modules/webhooks/schemas/webhook_schema.py
Schemas for the webhooks module.
"""

from typing import Any

from pydantic import Field

from app.shared.schemas.base import BaseSchema


class WebhookEventResponse(BaseSchema):
    """Response returned to GitHub after receiving a webhook."""
    status: str
    message: str
    job_id: str | None = None


class GitHubPushPayload(BaseSchema):
    """Schema for the GitHub push event payload."""
    ref: str
    before: str
    after: str
    repository: dict[str, Any]
    pusher: dict[str, Any]
    sender: dict[str, Any]
    commits: list[dict[str, Any]] = Field(default_factory=list)
    head_commit: dict[str, Any] | None = None
