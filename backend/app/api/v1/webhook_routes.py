"""
app/api/v1/webhook_routes.py
GitHub webhook API routes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.core.exceptions import WebhookVerificationError
from app.core.logging import get_logger
from app.dependencies import get_webhook_service
from app.infrastructure.github.webhook_verifier import verify_webhook_payload
from app.modules.webhooks.schemas.webhook_schema import WebhookEventResponse
from app.modules.webhooks.service.webhook_service import WebhookService

logger = get_logger(__name__)
router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.post("/github", response_model=WebhookEventResponse, status_code=status.HTTP_200_OK)
async def github_webhook(
    request: Request,
    x_github_event: str = Header(..., alias="X-GitHub-Event"),
    x_hub_signature_256: str = Header(..., alias="X-Hub-Signature-256"),
    x_github_delivery: str = Header(..., alias="X-GitHub-Delivery"),
    service: WebhookService = Depends(get_webhook_service),
) -> WebhookEventResponse:
    """
    Receive GitHub push webhooks.
    Verifies HMAC-SHA256 signature, checks idempotency, and enqueues ingestion.
    """
    logger.info("received_github_webhook", event_type=x_github_event, delivery_id=x_github_delivery)
    
    from starlette.requests import ClientDisconnect
    try:
        raw_body = await request.body()
    except ClientDisconnect:
        raw_body = getattr(request, "_body", b"")
        if not raw_body:
            logger.warning("github_webhook_client_disconnected_early", delivery_id=x_github_delivery)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Client disconnected before payload body transfer completed.")

    # HMAC signature verification
    try:
        verify_webhook_payload(raw_body, x_hub_signature_256)
    except WebhookVerificationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))


    # Parse and process
    import json
    try:
        payload = json.loads(raw_body)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload.")

    return await service.handle_event(
        event_type=x_github_event,
        delivery_id=x_github_delivery,
        payload=payload,
    )
