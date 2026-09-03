"""
app/api/v1/webhooks.py
API endpoints for GitHub webhooks.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import IngestionSource, JobStatus
from app.core.exceptions import ConfigurationError, WebhookVerificationError
from app.infrastructure.cache.redis_client import acquire_lock
from app.infrastructure.database.models.ingestion_job import IngestionJob
from app.infrastructure.database.models.repository import Repository
from app.infrastructure.database.models.webhook_event import WebhookEvent
from app.infrastructure.database.session import get_db
from app.infrastructure.github.webhook_verifier import verify_webhook_payload

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.post("/github")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(...),
    x_github_delivery: str = Header(...),
    x_hub_signature_256: str = Header(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Handle GitHub webhook payloads.
    """
    if not x_hub_signature_256:
        raise HTTPException(status_code=401, detail="Missing X-Hub-Signature-256 header.")
        
    payload_body = await request.body()
    
    try:
        verify_webhook_payload(payload_body, x_hub_signature_256)
    except WebhookVerificationError:
        raise HTTPException(status_code=401, detail="Invalid webhook signature.")
    except ConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
        
    payload_json = await request.json()
    
    # We only care about push events
    if x_github_event != "push":
        return {"status": "ignored", "reason": f"Unhandled event type: {x_github_event}"}
        
    # Idempotency check via Redis lock (prevents race conditions if GH retries)
    lock_key = f"webhook_lock:{x_github_delivery}"
    if not await acquire_lock(lock_key, ttl_seconds=60):
        return {"status": "ignored", "reason": "Webhook already being processed."}
        
    # Check if we already processed this delivery in the DB
    existing_event = await db.execute(
        select(WebhookEvent).where(WebhookEvent.delivery_id == x_github_delivery)
    )
    if existing_event.scalar_one_or_none():
        return {"status": "ignored", "reason": "Webhook delivery already processed."}
        
    repo_full_name = payload_json.get("repository", {}).get("full_name")
    if not repo_full_name:
        raise HTTPException(status_code=400, detail="Missing repository full_name in payload.")
        
    # Find matching registered repository
    repo_result = await db.execute(
        select(Repository).where(Repository.full_name == repo_full_name)
    )
    repo = repo_result.scalar_one_or_none()
    
    if not repo:
        return {"status": "ignored", "reason": f"Repository {repo_full_name} is not registered."}
        
    # Track the event
    head_commit = payload_json.get("head_commit", {}).get("id")
    event = WebhookEvent(
        repository_id=repo.id,
        delivery_id=x_github_delivery,
        event_type=x_github_event,
        ref=payload_json.get("ref"),
        head_commit=head_commit,
        payload=payload_json,
    )
    db.add(event)
    
    # Create an ingestion job
    job = IngestionJob(
        repository_id=repo.id,
        source=IngestionSource.WEBHOOK.value,
        status=JobStatus.QUEUED.value,
        commit_sha=head_commit,
    )
    db.add(job)
    
    await db.flush()
    event.job_id = job.id
    
    await db.commit()
    
    # In a fully integrated system, dispatch Celery task here:
    # process_ingestion_job.delay(str(job.id))
    
    return {
        "status": "accepted",
        "job_id": str(job.id),
        "delivery_id": x_github_delivery,
    }
