"""
app/workers/celery_app.py
Entry point for Celery workers.

Usage:
    celery -A app.workers.celery_app worker --loglevel=INFO -Q ingestion
"""

import asyncio

from celery.signals import worker_process_init, worker_process_shutdown

from app.core.logging import configure_logging, get_logger
from app.infrastructure.celery.celery_client import celery_app

logger = get_logger(__name__)


@worker_process_init.connect
def init_worker(**kwargs: dict) -> None:
    """
    Initialize connections (Database, Qdrant, Redis) for each worker process.
    Because Celery forks processes, we must initialize async connections inside
    the child process to avoid event loop sharing errors.
    """
    configure_logging(json_logs=True)
    logger.info("celery_worker_init")
    
    # Run the async initialization functions in an event loop
    loop = asyncio.get_event_loop()
    
    from app.infrastructure.cache.redis_client import init_redis
    from app.infrastructure.database.session import init_db
    from app.infrastructure.qdrant.client import init_qdrant
    
    loop.run_until_complete(init_redis())
    loop.run_until_complete(init_db())
    loop.run_until_complete(init_qdrant())
    
    logger.info("celery_worker_ready")


@worker_process_shutdown.connect
def shutdown_worker(**kwargs: dict) -> None:
    """
    Close connections when the worker shuts down.
    """
    logger.info("celery_worker_shutdown")
    
    loop = asyncio.get_event_loop()
    
    from app.infrastructure.cache.redis_client import close_redis
    from app.infrastructure.database.session import close_db
    from app.infrastructure.qdrant.client import close_qdrant
    
    loop.run_until_complete(close_redis())
    loop.run_until_complete(close_db())
    loop.run_until_complete(close_qdrant())
