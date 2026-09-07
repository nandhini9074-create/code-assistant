"""
app/modules/search/domain/search_domain.py

Domain models for the search pipeline.
"""

from dataclasses import dataclass, field
from typing import Any

from app.core.enums import IntentType


@dataclass
class RetrievedChunk:
    """Represents a code chunk retrieved during search."""

    chunk_hash: str
    file_path: str
    content: str
    score: float
    metadata: dict[str, Any]


@dataclass
class SearchContext:
    """Context object passed through search pipeline stages."""

    repo_id: str
    query: str

    # Repository information
    repo_owner: str | None = None
    repo_name: str | None = None
    qdrant_collection: str | None = None

    # Intent and query understanding
    intent: IntentType | None = None
    intent_parameters: dict[str, Any] = field(default_factory=dict)

    keywords: list[str] = field(default_factory=list)
    identifiers: list[str] = field(default_factory=list)
    file_paths: list[str] = field(default_factory=list)
    repo_hint: str | None = None
    language_hint: str | None = None

    # Retrieval
    query_vector: list[float] | None = None
    retrieved_chunks: list[RetrievedChunk] = field(default_factory=list)

    # Code identification
    identified_elements: list[dict[str, Any]] = field(default_factory=list)
    target_symbol: str | None = None
    primary_chunk: RetrievedChunk | None = None

    # Analysis context
    code_snippets: list[dict[str, Any]] = field(default_factory=list)
    llm_context: str | None = None
    analysis_result: dict[str, Any] | None = None

    # Validation state (Step 10)
    validated: bool = False
    validation_status: str | None = None
    validation_errors: list[str] = field(default_factory=list)
    validation_retries: int = 0
    validation_feedback: list[str] = field(default_factory=list)

    # Action Analysis & Triage (Steps 11 & 12)
    action_analysis: dict[str, Any] | None = None
    triage_result: dict[str, Any] | None = None

    # Pipeline control
    insufficient_evidence: bool = False
    early_exit: str | None = None
    early_exit_message: str | None = None

    # Final output
    final_response: Any = None


@dataclass
class SearchResult:
    """Result of a search pipeline execution."""

    success: bool
    response: Any | None = None
    error_message: str | None = None