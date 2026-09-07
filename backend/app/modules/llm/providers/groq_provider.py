
"""
app/modules/llm/providers/groq_provider.py

Groq LLM provider using Groq's OpenAI-compatible API.
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
from app.modules.llm.schemas.llm_schema import LLMResponse


logger = get_logger(__name__)


class GroqProvider(BaseLLMProvider):
    """
    Implementation of the LLM provider using the Groq API.

    Groq provides an OpenAI-compatible API, so AsyncOpenAI can be used
    as the client while the model and credentials come from settings.
    """

    def __init__(self) -> None:
        self.settings = get_settings()

        if not self.settings.groq_api_key:
            logger.warning("groq_api_key_missing")

        self.client = AsyncOpenAI(
            api_key=self.settings.groq_api_key or "dummy-key-for-tests",
            base_url=self.settings.groq_base_url,
            timeout=float(self.settings.groq_timeout_seconds),
            max_retries=self.settings.groq_max_retries,
        )

    async def complete(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """
        Generate a text completion using the configured Groq model.
        """

        messages: list[dict[str, str]] = []

        if system_prompt:
            messages.append(
                {
                    "role": "system",
                    "content": system_prompt,
                }
            )

        messages.append(
            {
                "role": "user",
                "content": prompt,
            }
        )

        try:
            response = await self.client.chat.completions.create(
                model=self.settings.groq_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            content = response.choices[0].message.content

            if not content:
                raise LLMError(
                    "LLM returned an empty response"
                )

            usage: dict[str, int] = {}

            if response.usage:
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }

            return LLMResponse(
                text=content,
                provider="groq",
                model=self.settings.groq_model,
                usage=usage,
            )

        except Exception as exc:
            if isinstance(exc, LLMError):
                raise

            logger.error(
                "groq_generation_failed",
                exc_info=exc,
            )

            raise LLMError(
                f"Groq API request failed: {exc}"
            ) from exc

    async def complete_json(
        self,
        prompt: str,
        system_prompt: str | None = None,
        schema: dict[str, Any] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        """
        Generate a structured JSON response using Groq.
        """

        sys_prompt = (
            system_prompt
            or "You are a helpful assistant."
        )

        if schema:
            enhanced_system_prompt = (
                f"{sys_prompt}\n\n"
                "You MUST output raw, valid JSON only. "
                "Do not use markdown code blocks. "
                "Your response must strictly conform to "
                "the following JSON schema:\n"
                f"{json.dumps(schema, indent=2)}"
            )
        else:
            enhanced_system_prompt = (
                f"{sys_prompt}\n\n"
                "You MUST output raw, valid JSON only. "
                "Do not use markdown formatting."
            )

        messages = [
            {
                "role": "system",
                "content": enhanced_system_prompt,
            },
            {
                "role": "user",
                "content": prompt,
            },
        ]

        try:
            response = await self.client.chat.completions.create(
                model=self.settings.groq_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={
                    "type": "json_object"
                },
            )

            content = response.choices[0].message.content

            if not content:
                raise LLMError(
                    "LLM returned an empty response"
                )

            try:
                parsed = json.loads(content)

            except json.JSONDecodeError as exc:
                raise LLMParseError(
                    "Failed to parse Groq response as JSON: "
                    f"{exc}"
                ) from exc

            if not isinstance(parsed, dict):
                raise LLMParseError(
                    "Groq JSON response must be an object"
                )

            return parsed

        except Exception as exc:
            if isinstance(
                exc,
                (LLMError, LLMParseError),
            ):
                raise

            logger.error(
                "groq_structured_generation_failed",
                exc_info=exc,
            )

            raise LLMError(
                f"Groq API request failed: {exc}"
            ) from exc

    async def generate_response(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """
        Generate a normal text response.
        """

        temp = (
            temperature
            if temperature is not None
            else LLM_DEFAULT_TEMPERATURE
        )

        max_t = (
            max_tokens
            if max_tokens is not None
            else self.settings.groq_max_tokens
        )

        response = await self.complete(
            prompt=user_prompt,
            system_prompt=system_prompt,
            max_tokens=max_t,
            temperature=temp,
        )

        return response.text

    async def generate_structured_response(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """
        Generate a structured JSON response.
        """

        temp = (
            temperature
            if temperature is not None
            else LLM_DEFAULT_TEMPERATURE
        )

        return await self.complete_json(
            prompt=user_prompt,
            system_prompt=system_prompt,
            schema=schema,
            max_tokens=self.settings.groq_max_tokens,
            temperature=temp,
        )

