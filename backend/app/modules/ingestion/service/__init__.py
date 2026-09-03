"""
app/modules/ingestion/service/__init__.py
"""
from app.modules.ingestion.service.ingestion_service import IngestionService
from app.modules.ingestion.service.zip_ingestion_service import ZipIngestionService

__all__ = ["IngestionService", "ZipIngestionService"]
