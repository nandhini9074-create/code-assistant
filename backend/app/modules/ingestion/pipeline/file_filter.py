"""
app/modules/ingestion/pipeline/file_filter.py
Pipeline stage: Filter files.
"""

from app.modules.ingestion.domain.ingestion_domain import IngestionContext
from app.shared.utils.file_utils import get_language_from_extension


class FileFilterStage:
    IGNORED_DIRS = {".git", "node_modules", "venv", "dist", "build", "vendor"}
    
    async def execute(self, context: IngestionContext) -> None:
        """Filters out unwanted files."""
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
