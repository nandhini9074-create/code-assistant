"""
app/modules/llm/schemas/llm_schema.py
Schemas for the LLM module.
"""

from typing import Any

from pydantic import Field

from app.core.enums import IntentType
from app.shared.schemas.base import BaseSchema


class LLMRequest(BaseSchema):
    """Standard request to the LLM service."""
    prompt: str
    system_prompt: str | None = None
    max_tokens: int = 1024
    temperature: float = 0.0


class LLMResponse(BaseSchema):
    """Standard response from the LLM service."""
    text: str
    provider: str
    model: str
    usage: dict[str, int] = Field(default_factory=dict)


class IntentClassificationResult(BaseSchema):
    """Result of intent classification."""
    intent: IntentType
    parameters: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 1.0


class CodeElement(BaseSchema):
    """Identified code element from a query."""
    name: str
    type: str  # e.g., 'function', 'class', 'variable'
    context: str | None = None
