"""
app/modules/llm/providers/claude_provider.py
Claude provider stub.
"""

from typing import Any

from app.modules.llm.providers.base import BaseLLMProvider
from app.modules.llm.schemas.llm_schema import LLMResponse


class ClaudeProvider(BaseLLMProvider):
    """
    Claude provider implementation.
    Currently a placeholder for future implementation as per project spec.
    """
    
    def __init__(self) -> None:
        pass
        
    async def complete(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> LLMResponse:
        raise NotImplementedError("Claude provider is a future placeholder.")

    async def complete_json(
        self,
        prompt: str,
        system_prompt: str | None = None,
        schema: dict[str, Any] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        raise NotImplementedError("Claude provider is a future placeholder.")
