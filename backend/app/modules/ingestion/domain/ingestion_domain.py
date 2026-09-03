"""
app/modules/ingestion/domain/ingestion_domain.py
Domain models for the ingestion pipeline.
"""

from dataclasses import dataclass, field
from typing import Any

from app.core.enums import IngestionSource


@dataclass
class ChunkRecord:
    """Represents a code chunk during ingestion."""
    file_path: str
    chunk_hash: str
    content: str
    metadata: dict[str, Any]
    point_id: str | None = None
    embedding: list[float] | None = None
    is_new: bool = True


@dataclass
class FileRecord:
    """Represents a file during ingestion."""
    file_path: str
    blob_sha: str
    file_hash: str
    content: bytes | None = None
    chunks: list[ChunkRecord] = field(default_factory=list)
    is_new_or_modified: bool = True
    size: int = 0


@dataclass
class PipelineResult:
    """Result of an ingestion pipeline execution."""
    success: bool
    job_id: str
    processed_files_count: int = 0
    indexed_chunks_count: int = 0
    error_message: str | None = None


@dataclass
class IngestionContext:
    """Context object passed through the pipeline stages."""
    job_id: str
    repo_id: str
    source: IngestionSource
    commit_sha: str
    files: list[FileRecord] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)
    extracted_zip_path: str | None = None
    github_token: str | None = None
