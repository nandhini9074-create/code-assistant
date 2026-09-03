"""
app/infrastructure/celery/celery_client.py
Celery application instance and configuration.
"""

from celery import Celery

from app.config import get_settings
from app.core.constants import (
    CELERY_CLEANUP_QUEUE,
    CELERY_INGESTION_QUEUE,
    CELERY_MAINTENANCE_QUEUE,
)


def make_celery() -> Celery:
    """
    Create and configure the Celery application.
    """
    settings = get_settings()

    celery_app = Celery(
        "code_explorer",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
    )

    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        # Allow running tasks synchronously during tests
        task_always_eager=settings.celery_task_always_eager,
        # Define explicit queues
        task_default_queue=CELERY_INGESTION_QUEUE,
        task_queues={
            CELERY_INGESTION_QUEUE: {
                "exchange": CELERY_INGESTION_QUEUE,
                "routing_key": CELERY_INGESTION_QUEUE,
            },
            CELERY_CLEANUP_QUEUE: {
                "exchange": CELERY_CLEANUP_QUEUE,
                "routing_key": CELERY_CLEANUP_QUEUE,
            },
            CELERY_MAINTENANCE_QUEUE: {
                "exchange": CELERY_MAINTENANCE_QUEUE,
                "routing_key": CELERY_MAINTENANCE_QUEUE,
            },
        },
        # Route specific tasks to specific queues
        task_routes={
            "app.workers.tasks.ingestion_tasks.*": {"queue": CELERY_INGESTION_QUEUE},
            "app.workers.tasks.cleanup_tasks.*": {"queue": CELERY_CLEANUP_QUEUE},
            "app.workers.tasks.maintenance_tasks.*": {"queue": CELERY_MAINTENANCE_QUEUE},
        },
    )
    
    # Auto-discover tasks in all worker task modules
    celery_app.autodiscover_tasks(
        [
            "app.workers.tasks",
        ],
        force=True,
    )

    return celery_app


# The singleton Celery app instance to be imported by workers and API
celery_app = make_celery()
