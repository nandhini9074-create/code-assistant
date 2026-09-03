"""
app/modules/webhooks/schemas/__init__.py
"""
from app.modules.webhooks.schemas.webhook_schema import GitHubPushPayload, WebhookEventResponse

__all__ = ["GitHubPushPayload", "WebhookEventResponse"]
