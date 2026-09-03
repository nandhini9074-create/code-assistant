"""
app/modules/llm/providers/base.py
Base LLM provider interface.
"""

from abc import ABC, abstractmethod
from typing import Any

from app.modules.llm.schemas.llm_schema import LLMResponse


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers."""
    
    @abstractmethod
    async def complete(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """
        Generate a text completion from the LLM.
        """
        pass

    @abstractmethod
    async def complete_json(
        self,
        prompt: str,
        system_prompt: str | None = None,
        schema: dict[str, Any] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        """
        Generate a structured JSON response from the LLM.
        """
        pass
