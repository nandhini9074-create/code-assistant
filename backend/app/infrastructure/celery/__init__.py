"""
app/infrastructure/celery/__init__.py
Celery infrastructure module.
"""

from app.infrastructure.celery.celery_client import celery_app

__all__ = [
    "celery_app",
]
