"""
evaluation/config.py
Configuration models and defaults for the evaluation framework.
"""

from __future__ import annotations

from pathlib import Path
from typing import Set

from pydantic import BaseModel, Field

from app.core.enums import IntentType

# Canonical set of supported intents across RepoLens
SUPPORTED_INTENTS: Set[IntentType] = {
    IntentType.RETRIEVE,
    IntentType.ADD_FEATURE,
    IntentType.FIX_BUG,
    IntentType.FIX_VULNERABILITY,
}

SUPPORTED_INTENT_VALUES: Set[str] = {intent.value for intent in SUPPORTED_INTENTS}


class EvaluationConfig(BaseModel):
    """Configuration options for dataset loading, validation, and evaluation runs."""

    default_dataset_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent / "datasets"
    )
    min_relevance_grade: float = Field(
        default=0.0,
        description="Minimum allowed numeric relevance grade (typically 0.0).",
    )
    max_relevance_grade: float = Field(
        default=4.0,
        description="Maximum allowed numeric relevance grade (e.g. 0-4 graded scale or 0-1 binary).",
    )
    strict_validation: bool = Field(
        default=True,
        description="If True, raise error on any validation failure; if False, collect warnings.",
    )
    default_retrieval_limit: int = Field(
        default=20,
        description="Default number of code chunks to retrieve during retrieval evaluation.",
    )
    case_sensitive_intents: bool = Field(
        default=False,
        description="Whether intent string matching should be strictly uppercase.",
    )

    class Config:
        arbitrary_types_allowed = True


_default_config: EvaluationConfig | None = None


def get_evaluation_config() -> EvaluationConfig:
    """Retrieve or initialize the global evaluation configuration instance."""
    global _default_config
    if _default_config is None:
        _default_config = EvaluationConfig()
    return _default_config


def set_evaluation_config(config: EvaluationConfig) -> None:
    """Override the global evaluation configuration instance."""
    global _default_config
    _default_config = config
