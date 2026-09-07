"""
app/core/constants.py
Application-wide constants for Code Explorer.
No business logic — pure configuration values.
"""

from __future__ import annotations

# File Size Limits

# Maximum size of a single file to fetch and process (bytes)
MAX_FILE_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 MB

# Maximum total extracted size from a ZIP archive (bytes)
MAX_ZIP_TOTAL_SIZE_BYTES: int = 500 * 1024 * 1024  # 500 MB

# Maximum number of files inside a ZIP archive
MAX_ZIP_FILE_COUNT: int = 10_000

# Maximum size of a single file inside a ZIP archive (bytes)
MAX_ZIP_SINGLE_FILE_BYTES: int = 50 * 1024 * 1024  # 50 MB


# Chunking

# Maximum tokens per chunk before sub-splitting
CHUNK_MAX_TOKENS: int = 512

# Token overlap between consecutive sub-chunks
CHUNK_OVERLAP_TOKENS: int = 64

# Minimum chunk size to index (skip trivial 1-liner chunks)
CHUNK_MIN_TOKENS: int = 10

# Maximum characters for a raw_code payload stored in Qdrant
CHUNK_MAX_RAW_CODE_CHARS: int = 8_000


# Embedding

# Default Jina embedding batch size
EMBEDDING_BATCH_SIZE: int = 32

# Default vector dimension (jina-embeddings-v3)
DEFAULT_EMBEDDING_DIMENSION: int = 1024

# Maximum retries for embedding API calls
EMBEDDING_MAX_RETRIES: int = 3

# Base delay for embedding retry backoff (seconds)
EMBEDDING_RETRY_BASE_DELAY: float = 1.0

# Maximum delay cap for embedding retry (seconds)
EMBEDDING_RETRY_MAX_DELAY: float = 60.0


# LLM

# Maximum tokens to send in one LLM context
LLM_MAX_CONTEXT_TOKENS: int = 8_192

# Maximum tokens in a single LLM response
LLM_MAX_RESPONSE_TOKENS: int = 4_096

# Default LLM temperature for deterministic analysis
LLM_DEFAULT_TEMPERATURE: float = 0.1

# Maximum retries for LLM API calls
LLM_MAX_RETRIES: int = 3


# Search / Retrieval

# Number of candidate chunks returned from Qdrant per retrieval pass
SEARCH_TOP_K: int = 20

# Number of final chunks passed to the LLM after reranking
SEARCH_RERANKED_TOP_K: int = 10

# Minimum similarity score to consider a chunk relevant
SEARCH_MIN_SCORE: float = 0.4

# Minimum evidence score before calling the LLM (below = insufficient evidence)
MIN_EVIDENCE_SCORE: float = 0.5

# High confidence threshold
CONFIDENCE_HIGH: float = 0.8

# Medium confidence threshold
CONFIDENCE_MEDIUM: float = 0.5

# Low confidence threshold (below this = NONE)
CONFIDENCE_LOW: float = 0.3


# GitHub API

GITHUB_API_BASE_URL: str = "https://api.github.com"

# GitHub API version header
GITHUB_API_VERSION: str = "2022-11-28"

# Accept header for GitHub JSON API
GITHUB_ACCEPT_JSON: str = "application/vnd.github+json"

# Accept header for raw file content
GITHUB_ACCEPT_RAW: str = "application/vnd.github.v3.raw"

# Maximum retries for GitHub API calls
GITHUB_MAX_RETRIES: int = 3

# Base delay for GitHub retry backoff (seconds)
GITHUB_RETRY_BASE_DELAY: float = 1.0

# GitHub rate-limit remaining header
GITHUB_RATELIMIT_REMAINING_HEADER: str = "X-RateLimit-Remaining"

# GitHub rate-limit reset header (Unix timestamp)
GITHUB_RATELIMIT_RESET_HEADER: str = "X-RateLimit-Reset"


# Webhook

# GitHub signature header
GITHUB_SIGNATURE_HEADER: str = "X-Hub-Signature-256"

# GitHub delivery ID header (idempotency key)
GITHUB_DELIVERY_HEADER: str = "X-GitHub-Delivery"

# GitHub event type header
GITHUB_EVENT_HEADER: str = "X-GitHub-Event"

# Hash algorithm prefix in signature header
GITHUB_SIGNATURE_PREFIX: str = "sha256="


# Qdrant

# Default collection name for all code chunk vectors
QDRANT_CODE_COLLECTION: str = "code_chunks"

# Payload field used for repository scoping filter
QDRANT_REPO_ID_FIELD: str = "repo_id"

# UUID namespace for deterministic Qdrant point IDs
# Generated once: uuid.uuid5(uuid.NAMESPACE_DNS, "code-explorer.qdrant.points")
QDRANT_POINT_ID_NAMESPACE: str = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"


# Redis / Cache

# Default TTL for cached embeddings (seconds)
EMBEDDING_CACHE_TTL: int = 86_400  # 24 hours

# Key prefix for embedding cache
EMBEDDING_CACHE_PREFIX: str = "emb:"

# Key prefix for rate-limit counters
RATE_LIMIT_PREFIX: str = "rl:"

# Key prefix for idempotency / deduplication keys
IDEMPOTENCY_PREFIX: str = "idem:"

# TTL for idempotency keys (seconds)
IDEMPOTENCY_TTL: int = 86_400  # 24 hours


# File Filtering

# Directories to skip entirely during ingestion
EXCLUDED_DIRECTORIES: frozenset[str] = frozenset(
    {
        ".git",
        "node_modules",
        "vendor",
        "dist",
        "build",
        ".build",
        "coverage",
        ".coverage",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".venv",
        "venv",
        "env",
        ".env",
        "target",      # Rust / Java Maven
        "out",         # Java / Kotlin
        ".gradle",
        ".idea",
        ".vscode",
        "eggs",
        ".eggs",
        "htmlcov",
        "site-packages",
    }
)

# File extensions to skip (binary / media / generated)
EXCLUDED_EXTENSIONS: frozenset[str] = frozenset(
    {
        # Compiled / binary
        ".pyc", ".pyo", ".pyd", ".class", ".o", ".a", ".lib",
        ".dll", ".so", ".dylib", ".exe", ".bin", ".obj",
        # Archives
        ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
        # Media
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".ico",
        ".mp3", ".mp4", ".wav", ".avi", ".mov", ".mkv", ".webm",
        ".woff", ".woff2", ".ttf", ".otf", ".eot",
        # Documents
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        # Lock files
        ".lock", "package-lock.json", "yarn.lock", "Pipfile.lock",
        # Data / generated
        ".min.js", ".min.css", ".map",
        ".parquet", ".csv", ".tsv", ".db", ".sqlite", ".sqlite3",
        # Certificates
        ".pem", ".crt", ".key", ".cer",
    }
)

# Exact filenames to skip regardless of directory
EXCLUDED_FILENAMES: frozenset[str] = frozenset(
    {
        ".DS_Store",
        "Thumbs.db",
        ".gitignore",
        ".gitattributes",
        ".editorconfig",
        "CHANGELOG.md",
        "CHANGES.md",
        "LICENSE",
        "LICENSE.md",
        "LICENSE.txt",
    }
)

# Mapping from file extension → programming language
EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".scala": "scala",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".md": "markdown",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".xml": "xml",
    ".html": "html",
    ".css": "css",
    ".sql": "sql",
}

# Languages supported by tree-sitter (AST-aware chunking)
TREE_SITTER_LANGUAGES: frozenset[str] = frozenset(
    {"python", "javascript", "typescript", "java", "go", "rust"}
)


# Celery

CELERY_INGESTION_QUEUE: str = "ingestion"
CELERY_CLEANUP_QUEUE: str = "cleanup"
CELERY_MAINTENANCE_QUEUE: str = "maintenance"

# Maximum retries for Celery ingestion tasks
CELERY_INGESTION_MAX_RETRIES: int = 3

# Retry countdown (seconds) for failed ingestion tasks
CELERY_INGESTION_RETRY_COUNTDOWN: int = 60


# API

# Maximum query length for search endpoint
SEARCH_MAX_QUERY_LENGTH: int = 2_000

# Maximum length for repository name / URL in registration
REPO_URL_MAX_LENGTH: int = 500

# Default page size for paginated list endpoints
DEFAULT_PAGE_SIZE: int = 20

# Maximum page size allowed
MAX_PAGE_SIZE: int = 100
