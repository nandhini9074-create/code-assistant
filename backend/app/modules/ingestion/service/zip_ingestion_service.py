"""
app/modules/ingestion/service/zip_ingestion_service.py
Service that handles ZIP-specific ingestion logic.
"""

from typing import IO

from app.core.enums import IngestionSource
from app.infrastructure.storage.zip_storage import ZipStorageManager
from app.modules.ingestion.domain.ingestion_domain import PipelineResult
from app.modules.ingestion.service.ingestion_service import IngestionService


class ZipIngestionService:
    def __init__(self, ingestion_service: IngestionService) -> None:
        self.ingestion_service = ingestion_service
        self.zip_manager = ZipStorageManager()

    async def process_zip(
        self,
        job_id: str,
        repo_id: str,
        commit_sha: str,
        zip_file: IO[bytes],
    ) -> PipelineResult:
        """Processes a ZIP file and kicks off the ingestion pipeline."""
        extracted_path = None
        try:
            extracted_path = self.zip_manager.extract_securely(zip_file)
            
            # Run the pipeline with the local path
            return await self.ingestion_service.run_pipeline(
                job_id=job_id,
                repo_id=repo_id,
                source=IngestionSource.ZIP_UPLOAD,
                commit_sha=commit_sha,
                extracted_zip_path=extracted_path,
            )
        finally:
            if extracted_path:
                self.zip_manager.cleanup(extracted_path)
