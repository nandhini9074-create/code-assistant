
"""
app/modules/llm/providers/groq_provider.py

Groq LLM provider using Groq's OpenAI-compatible API.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
import structlog.contextvars
from openai import AsyncOpenAI

from app.config import get_settings
from app.core.constants import LLM_DEFAULT_TEMPERATURE
from app.core.exceptions import LLMError, LLMParseError
from app.core.logging import get_logger
from app.modules.llm.providers.base import BaseLLMProvider
from app.modules.llm.schemas.llm_schema import LLMResponse


logger = get_logger(__name__)


def _extract_tokens(usage: Any) -> tuple[int, int, int]:
    """Safely extract prompt, completion, and total token counts."""

    if not usage:
        return 0, 0, 0

    if isinstance(usage, dict):
        return (
            int(usage.get("prompt_tokens") or 0),
            int(usage.get("completion_tokens") or 0),
            int(usage.get("total_tokens") or 0),
        )

    return (
        int(getattr(usage, "prompt_tokens", 0) or 0),
        int(getattr(usage, "completion_tokens", 0) or 0),
        int(getattr(usage, "total_tokens", 0) or 0),
    )


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
        Generate a normal text completion using Groq.
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

            if not response.choices:
                raise LLMError("LLM returned an empty response")

            content = response.choices[0].message.content

            if not content:
                raise LLMError("LLM returned an empty response")

            ctx_vars = structlog.contextvars.get_contextvars()

            inp_t, out_t, total_t = _extract_tokens(
                getattr(response, "usage", None)
            )

            logger.info(
                "groq_token_usage",
                provider="groq",
                model=self.settings.groq_model,
                stage=ctx_vars.get("stage"),
                request_id=ctx_vars.get("request_id"),
                input_tokens=inp_t,
                output_tokens=out_t,
                total_tokens=total_t,
            )

            usage: dict[str, int] = {}

            if getattr(response, "usage", None):
                usage = {
                    "prompt_tokens": inp_t,
                    "completion_tokens": out_t,
                    "total_tokens": total_t,
                }

            return LLMResponse(
                text=content,
                provider="groq",
                model=self.settings.groq_model,
                usage=usage,
            )

        except LLMError:
            raise

        except Exception as exc:
            logger.error(
                "groq_generation_failed",
                exc_info=exc,
            )

            # Propagate the failure to the calling pipeline stage.
            # The stage is responsible for applying its deterministic
            # fallback instead of the provider inventing a response.
            raise LLMError(
                f"Groq API request failed: {exc}"
            ) from exc

    async def complete_json(
        self,
        prompt: str,
        system_prompt: str | None = None,
        schema: dict[str, Any] | None = None,
        max_tokens: int = 300,
        temperature: float = 0.0,
    ) -> dict[str, Any]:


         # TEMPORARY TEST
        """
        Generate a structured JSON object using Groq.

        Groq is requested to return a JSON object through the
        OpenAI-compatible response_format option.
        """

        base_prompt = (
            system_prompt
            or "You are a helpful assistant."
        )

        if schema:
            enhanced_system_prompt = (
                f"{base_prompt}\n\n"
                "Return only valid JSON.\n"
                "The response must conform to this schema:\n"
                f"{json.dumps(schema, separators=(',', ':'))}"
            )
        else:
            enhanced_system_prompt = (
                f"{base_prompt}\n\n"
                "Return only valid JSON."
            )

        messages: list[dict[str, str]] = [
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
                    "type": "json_object",
                },
            )

            if not response.choices:
                raise LLMError("LLM returned an empty response")

            content = response.choices[0].message.content

            if not content:
                raise LLMError("LLM returned an empty response")

            try:
                parsed = json.loads(content)

            except json.JSONDecodeError as exc:
                raise LLMParseError(
                    f"Failed to parse Groq response as JSON: {exc}"
                ) from exc

            if not isinstance(parsed, dict):
                raise LLMParseError(
                    "Groq JSON response must be an object"
                )

            ctx_vars = structlog.contextvars.get_contextvars()

            inp_t, out_t, total_t = _extract_tokens(
                getattr(response, "usage", None)
            )

            logger.info(
                "groq_token_usage",
                provider="groq",
                model=self.settings.groq_model,
                stage=ctx_vars.get("stage"),
                request_id=ctx_vars.get("request_id"),
                input_tokens=inp_t,
                output_tokens=out_t,
                total_tokens=total_t,
            )

            return parsed

        except LLMParseError:
            raise

        except LLMError:
            raise

        except Exception as exc:
            logger.error(
                "groq_structured_generation_failed",
                exc_info=exc,
            )

            # Propagate the failure to the calling pipeline stage.
            # The stage handles the appropriate deterministic fallback.
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
        max_tokens: int = 300,
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
            max_tokens=max_tokens,
            temperature=temp,
        )

