"""
evaluation/schemas.py
Pydantic schemas and domain models for evaluation datasets, queries, and relevance judgments.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterator, List, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.enums import IntentType
from evaluation.config import SUPPORTED_INTENT_VALUES, get_evaluation_config
from evaluation.exceptions import DatasetValidationError


class RelevanceGrade(BaseModel):
    """Encapsulates a numeric or categorical relevance grade."""

    score: float = Field(default=1.0, ge=0.0)
    label: Optional[str] = None
    description: Optional[str] = None


class RelevantChunk(BaseModel):
    """
    Represents a ground-truth relevant code chunk for an evaluation query.
    Can represent either a discrete chunk hash, point ID, or symbol location.
    """

    chunk_id: Optional[str] = Field(
        default=None,
        description="Stable chunk identifier (e.g. chunk hash, point ID, or symbol ID). Optional if file_path is provided.",
    )
    relevance_grade: float = Field(
        default=1.0,
        description="Relevance score (mandatory in dataset items, e.g. 1.0 for binary relevance, or 0-4 for graded relevance).",
    )
    file_path: Optional[str] = Field(default=None, description="Optional path to the source file.")
    symbol_name: Optional[str] = Field(default=None, description="Optional name of the target function/class/symbol.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary additional context.")

    @property
    def identifier(self) -> str:
        """Returns stable identifier: chunk_id if present, else file_path::symbol_name or file_path."""
        if self.chunk_id and self.chunk_id.strip():
            return self.chunk_id.strip()
        if self.file_path and self.file_path.strip():
            clean_fp = self.file_path.strip().replace("\\", "/")
            if self.symbol_name and self.symbol_name.strip():
                return f"{clean_fp}::{self.symbol_name.strip()}"
            return clean_fp
        return "unknown_chunk"

    @field_validator("chunk_id")
    @classmethod
    def validate_chunk_id(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValueError("chunk_id must be a non-empty string when provided.")
        return value.strip()

    @field_validator("relevance_grade")
    @classmethod
    def validate_relevance_grade(cls, value: Any) -> float:
        try:
            numeric_val = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"relevance_grade must be a numeric value, got {type(value).__name__} ({value}).")
        if numeric_val < 0.0:
            raise ValueError(f"relevance_grade must be non-negative, got {numeric_val}.")
        return numeric_val

    @model_validator(mode="after")
    def validate_chunk_identity(self) -> RelevantChunk:
        has_chunk_id = bool(self.chunk_id and self.chunk_id.strip())
        has_file_path = bool(self.file_path and self.file_path.strip())
        if not has_chunk_id and not has_file_path:
            raise ValueError("Expected chunk must provide either 'chunk_id' or 'file_path'.")
        return self


class EvaluationItem(BaseModel):
    """
    Represents a single evaluation test case consisting of a query,
    expected intent, optional collection/repository scope, and ground-truth chunks.
    """

    query_id: str = Field(..., description="Unique identifier for the evaluation query.")
    query: str = Field(..., description="The natural language or code search query text.")
    expected_intent: IntentType = Field(
        ...,
        description="The ground-truth intent type: RETRIEVE, ADD_FEATURE, FIX_BUG, OPTIMIZE, REFACTOR, FIX_VULNERABILITY.",
    )
    repository: Optional[str] = Field(
        default=None,
        description="Target repository name or URL if the evaluation is repository-scoped.",
    )
    collection_name: Optional[str] = Field(
        default=None,
        description="Specific Qdrant collection name if known or required.",
    )
    expected_chunks: List[RelevantChunk] = Field(
        default_factory=list,
        description="List of expected relevant code chunks with optional relevance grades.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional metadata such as difficulty, tags, author, or benchmark category.",
    )

    @field_validator("query_id")
    @classmethod
    def validate_query_id(cls, value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("query_id must be a non-empty string.")
        return value.strip()

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("query text must be a non-empty string.")
        return value.strip()

    @field_validator("expected_intent", mode="before")
    @classmethod
    def validate_expected_intent(cls, value: Any) -> IntentType:
        if isinstance(value, IntentType):
            return value

        if not isinstance(value, str):
            raise ValueError(
                f"expected_intent must be a string or IntentType enum, got {type(value).__name__} ({value})."
            )

        cleaned_value = value.strip().upper()
        if cleaned_value not in SUPPORTED_INTENT_VALUES:
            allowed = sorted(SUPPORTED_INTENT_VALUES)
            raise ValueError(
                f"Invalid intent '{value}'. Must be one of the 6 supported intents: {allowed}."
            )
        return IntentType(cleaned_value)

    @field_validator("expected_chunks", mode="before")
    @classmethod
    def coerce_expected_chunks(
        cls, value: Any
    ) -> List[Union[RelevantChunk, Dict[str, Any]]]:
        """
        Flexible parser allowing users to specify expected chunks as:
        1. A list of chunk_id strings: ["chunk_1", "chunk_2"]
        2. A dict of {chunk_id: grade}: {"chunk_1": 2.0, "chunk_2": 1.0}
        3. A list of dicts: [{"chunk_id": "chunk_1", "relevance_grade": 2.0}]
        """
        if value is None:
            return []

        if isinstance(value, dict):
            # Format: {"chunk_hash_1": 3.0, "chunk_hash_2": 1.0}
            return [
                {"chunk_id": str(cid), "relevance_grade": float(grade)}
                for cid, grade in value.items()
            ]

        if isinstance(value, list):
            coerced: List[Union[RelevantChunk, Dict[str, Any]]] = []
            for item in value:
                if isinstance(item, str):
                    coerced.append({"chunk_id": item, "relevance_grade": 1.0})
                elif isinstance(item, (dict, RelevantChunk)):
                    coerced.append(item)
                else:
                    raise ValueError(
                        f"Expected chunk entry must be a string, dict, or RelevantChunk; got {type(item).__name__}."
                    )
            return coerced

        raise ValueError(
            f"expected_chunks must be a list or dict, got {type(value).__name__}."
        )


class ValidationErrorDetail(BaseModel):
    """Detailed record of a single validation issue in an evaluation dataset."""

    item_index: Optional[int] = Field(default=None, description="0-based index of the item in the dataset.")
    query_id: Optional[str] = Field(default=None, description="query_id of the item if available.")
    field: str = Field(..., description="Field name where the error occurred.")
    error_type: str = Field(..., description="Category code (e.g. MISSING_FIELD, INVALID_INTENT, DUPLICATE_ID).")
    message: str = Field(..., description="Human-readable explanation of the validation failure.")


class ValidationResult(BaseModel):
    """Summary and details of dataset validation."""

    is_valid: bool = Field(..., description="True if no validation errors were found.")
    total_items: int = Field(default=0, description="Total number of items evaluated.")
    errors: List[ValidationErrorDetail] = Field(default_factory=list, description="List of validation errors.")
    warnings: List[str] = Field(default_factory=list, description="Non-fatal warnings.")
    intent_distribution: Dict[str, int] = Field(default_factory=dict, description="Counts of each intent in the dataset.")
    queries_with_chunks: int = Field(default=0, description="Count of queries that include expected chunks.")
    total_relevant_chunks: int = Field(default=0, description="Total count of ground-truth chunks across all queries.")

    def raise_for_status(self) -> None:
        """Raise DatasetValidationError if is_valid is False."""
        if not self.is_valid:
            error_count = len(self.errors)
            preview = "; ".join(e.message for e in self.errors[:3])
            if error_count > 3:
                preview += f" ... (+{error_count - 3} more errors)"
            raise DatasetValidationError(
                f"Dataset validation failed with {error_count} error(s): {preview}",
                validation_result=self,
            )


class EvaluationDataset(BaseModel):
    """
    Complete evaluation dataset containing a collection of evaluation items
    and associated metadata.
    """

    dataset_name: str = Field(default="RepoLens-Evaluation-Dataset", description="Name of the evaluation dataset.")
    version: str = Field(default="1.0", description="Dataset schema version.")
    description: Optional[str] = Field(default=None, description="Detailed description of the dataset purpose.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Dataset-level metadata.")
    items: List[EvaluationItem] = Field(default_factory=list, description="List of evaluation items.")

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self) -> Iterator[EvaluationItem]:
        return iter(self.items)

    def __getitem__(self, index: int) -> EvaluationItem:
        return self.items[index]

    def get_by_id(self, query_id: str) -> Optional[EvaluationItem]:
        """Find an item by its query_id."""
        cleaned_id = query_id.strip()
        for item in self.items:
            if item.query_id == cleaned_id:
                return item
        return None

    def filter_by_intent(self, intent: Union[IntentType, str]) -> List[EvaluationItem]:
        """Return a filtered list of items with the specified intent."""
        target_intent = (
            intent if isinstance(intent, IntentType) else IntentType(intent.strip().upper())
        )
        return [item for item in self.items if item.expected_intent == target_intent]

    def to_dict(self) -> Dict[str, Any]:
        """Convert dataset to a JSON-serializable Python dictionary."""
        return self.model_dump(mode="json")

    def to_json(self, indent: int = 2) -> str:
        """Serialize dataset to a formatted JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    def to_jsonl(self) -> str:
        """Serialize dataset items to JSON Lines format (one item per line)."""
        lines = []
        for item in self.items:
            lines.append(json.dumps(item.model_dump(mode="json")))
        return "\n".join(lines)
