"""
app/modules/llm/providers/qwen_provider.py
LLM provider implementation for Alibaba's Qwen models (via DashScope compatible mode).
"""

from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from app.config import get_settings
from app.core.constants import LLM_DEFAULT_TEMPERATURE
from app.core.exceptions import LLMError, LLMParseError
from app.core.logging import get_logger
from app.modules.llm.providers.base import BaseLLMProvider

logger = get_logger(__name__)


class QwenProvider(BaseLLMProvider):
    """
    Implementation of the Qwen LLM using the OpenAI-compatible DashScope API.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        
        if not self.settings.qwen_api_key:
            logger.warning("qwen_api_key_missing")
            
        self.client = AsyncOpenAI(
            api_key=self.settings.qwen_api_key or "dummy-key-for-tests",
            base_url=self.settings.qwen_base_url,
            timeout=float(self.settings.qwen_timeout_seconds),
            max_retries=self.settings.qwen_max_retries,
        )

    async def generate_response(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        temp = temperature if temperature is not None else LLM_DEFAULT_TEMPERATURE
        max_t = max_tokens if max_tokens is not None else self.settings.qwen_max_tokens

        try:
            response = await self.client.chat.completions.create(
                model=self.settings.qwen_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temp,
                max_tokens=max_t,
            )
            
            content = response.choices[0].message.content
            if not content:
                raise LLMError("LLM returned an empty response")
                
            return content

        except Exception as exc:
            logger.error("qwen_generation_failed", exc_info=exc)
            raise LLMError(f"Qwen API request failed: {exc}") from exc

    async def generate_structured_response(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """
        Qwen might not fully support native JSON schema enforcement in the exact 
        same way as OpenAI's strict mode, so we inject the schema requirement into 
        the system prompt and use response_format={"type": "json_object"}.
        """
        temp = temperature if temperature is not None else LLM_DEFAULT_TEMPERATURE
        
        # Inject schema instruction
        enhanced_system_prompt = (
            f"{system_prompt}\n\n"
            "You MUST output raw, valid JSON only. No markdown formatting blocks. "
            "Your response must strictly conform to this JSON schema:\n"
            f"{json.dumps(schema, indent=2)}"
        )

        try:
            response = await self.client.chat.completions.create(
                model=self.settings.qwen_model,
                messages=[
                    {"role": "system", "content": enhanced_system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temp,
                max_tokens=self.settings.qwen_max_tokens,
                response_format={"type": "json_object"},
            )
            
            content = response.choices[0].message.content
            if not content:
                raise LLMError("LLM returned an empty response")
                
            # Attempt to parse the JSON
            try:
                parsed = json.loads(content)
                return parsed
            except json.JSONDecodeError as exc:
                raise LLMParseError(f"Failed to parse LLM response as JSON: {exc}") from exc

        except Exception as exc:
            if isinstance(exc, LLMParseError):
                raise
            logger.error("qwen_structured_generation_failed", exc_info=exc)
            raise LLMError(f"Qwen API request failed: {exc}") from exc
