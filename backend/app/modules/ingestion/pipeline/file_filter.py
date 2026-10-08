"""
app/modules/ingestion/pipeline/file_filter.py
Pipeline stage: Filter files.
"""

from app.core.logging import get_logger
from app.modules.ingestion.domain.ingestion_domain import IngestionContext
from app.shared.utils.file_utils import get_language_from_extension

logger = get_logger(__name__)


class FileFilterStage:
    IGNORED_DIRS = {".git", "node_modules", "venv", "dist", "build", "vendor"}
    
    async def execute(self, context: IngestionContext) -> None:
        """Filters out unwanted files."""
        initial_count = len(context.files)
        logger.info("stage_3_file_filtering_started", initial_file_count=initial_count)
        filtered_files = []
        for file in context.files:
            # Skip hidden files or ignored directories
            parts = file.file_path.split("/")
            if any(p.startswith(".") for p in parts) or any(p in self.IGNORED_DIRS for p in parts):
                continue
                
            # Keep only supported languages or text files
            if get_language_from_extension(file.file_path) is not None:
                filtered_files.append(file)
                
        context.files = filtered_files
        logger.info(
            "stage_3_file_filtering_completed",
            initial_count=initial_count,
            retained_count=len(filtered_files),
            filtered_out_count=initial_count - len(filtered_files),
        )
