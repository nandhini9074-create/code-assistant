"""
app/core/enums.py
Application-wide enumerations for Code Explorer.
"""

from enum import Enum


# Intent
class IntentType(str, Enum):
    """Supported user intent types for code analysis."""

    RETRIEVE = "RETRIEVE"
    ADD_FEATURE = "ADD_FEATURE"
    FIX_BUG = "FIX_BUG"
    OPTIMIZE = "OPTIMIZE"
    REFACTOR = "REFACTOR"


# Job

class JobStatus(str, Enum):
    """Lifecycle states of an ingestion job."""

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PARTIAL = "partial"
    
class JobType(str, Enum):
    """Type of ingestion job."""
    
    FULL = "full"
    INCREMENTAL = "incremental"


class JobStage(str, Enum):
    """Granular pipeline stages tracked in job checkpoints."""

    INITIALIZING = "INITIALIZING"
    FETCHING_STRUCTURE = "FETCHING_STRUCTURE"
    FILTERING_FILES = "FILTERING_FILES"
    FETCHING_CONTENT = "FETCHING_CONTENT"
    CHECKING_HASHES = "CHECKING_HASHES"
    CHUNKING = "CHUNKING"
    DEDUPLICATING = "DEDUPLICATING"
    ENRICHING_METADATA = "ENRICHING_METADATA"
    GENERATING_EMBEDDINGS = "GENERATING_EMBEDDINGS"
    UPSERTING_VECTORS = "UPSERTING_VECTORS"
    CLEANING_DELETED = "CLEANING_DELETED"
    UPDATING_CHECKPOINT = "UPDATING_CHECKPOINT"
    COMPLETED = "COMPLETED"


# Ingestion

class TriggerSource(str, Enum):
    """Source type of an ingestion request."""

    GITHUB_URL = "github_url"
    ZIP_UPLOAD = "zip_upload"
    WEBHOOK = "webhook"


class FileFetchStatus(str, Enum):
    """Status of fetching content for a file."""

    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


# Repository

class RepositoryStatus(str, Enum):
    """Lifecycle states of a registered repository."""

    PENDING = "PENDING"        # Registered, not yet ingested
    INDEXING = "INDEXING"      # Ingestion in progress
    INDEXED = "INDEXED"        # Successfully indexed
    FAILED = "FAILED"          # Last ingestion failed
    STALE = "STALE"            # Indexed but behind HEAD


# File

class FileStatus(str, Enum):
    """Status of a file entry in the file registry."""

    ACTIVE = "ACTIVE"
    DELETED = "DELETED"


# Chunk

class SymbolType(str, Enum):
    """Type of a code chunk produced by AST chunking."""

    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    MODULE = "module"
    OTHER = "other"


# Language

class ProgrammingLanguage(str, Enum):
    """Supported programming languages for AST chunking."""

    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    JAVA = "java"
    GO = "go"
    RUST = "rust"
    UNKNOWN = "unknown"


# Webhook

class WebhookEventStatus(str, Enum):
    """Processing status of a received webhook event."""

    RECEIVED = "RECEIVED"
    PROCESSED = "PROCESSED"
    SKIPPED = "SKIPPED"        # Duplicate delivery or irrelevant branch
    FAILED = "FAILED"


class WebhookEventType(str, Enum):
    """GitHub webhook event types we handle."""

    PUSH = "push"
    PING = "ping"
    UNKNOWN = "unknown"


# Search

class RetrievalStrategy(str, Enum):
    """Retrieval strategy used during search."""

    DENSE = "dense"
    SPARSE = "sparse"
    HYBRID = "hybrid"


class ConfidenceLevel(str, Enum):
    """Confidence level of the AI analysis response."""

    HIGH = "high"      # > 0.8
    MEDIUM = "medium"  # 0.5 – 0.8
    LOW = "low"        # 0.3 – 0.5
    NONE = "none"      # < 0.3 or insufficient evidence
