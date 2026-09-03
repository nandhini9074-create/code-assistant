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
    
    # Populated by pipeline stages
    repo_owner: str | None = None
    repo_name: str | None = None
    qdrant_collection: str | None = None
    
    intent: IntentType | None = None
    intent_parameters: dict[str, Any] = field(default_factory=dict)
    
    keywords: list[str] = field(default_factory=list)
    identifiers: list[str] = field(default_factory=list)
    file_paths: list[str] = field(default_factory=list)
    
    query_vector: list[float] | None = None
    retrieved_chunks: list[RetrievedChunk] = field(default_factory=list)
    identified_elements: list[dict[str, Any]] = field(default_factory=list)
    llm_context: str | None = None
    
    insufficient_evidence: bool = False
    final_response: Any = None


@dataclass
class SearchResult:
    """Result of a search pipeline execution."""
    success: bool
    response: Any | None = None
    error_message: str | None = None
