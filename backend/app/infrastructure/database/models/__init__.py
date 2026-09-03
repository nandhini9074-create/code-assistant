"""
app/infrastructure/database/models/__init__.py
Exports all ORM models so Alembic autogenerate can discover them.

IMPORTANT: Every new model must be imported here.
Alembic's env.py imports this module, which causes all models to register
themselves with the Base metadata before migration generation.
"""

from app.infrastructure.database.models.chunk_registry import ChunkRegistry
from app.infrastructure.database.models.file_registry import FileRegistry
from app.infrastructure.database.models.ingestion_job import IngestionJob
from app.infrastructure.database.models.repository import Repository
from app.infrastructure.database.models.webhook_event import WebhookEvent

__all__ = [
    "Repository",
    "IngestionJob",
    "FileRegistry",
    "ChunkRegistry",
    "WebhookEvent",
]
