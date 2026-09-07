
"""
app/modules/llm/service/llm_service.py

Service layer for LLM interactions.
"""

from __future__ import annotations

from typing import Any

from app.core.enums import IntentType

from app.modules.llm.prompts.analysis_prompt import (
    ANALYSIS_SYSTEM_PROMPT,
    build_user_prompt,
)
from app.modules.llm.prompts.code_identification_prompt import (
    CODE_IDENTIFICATION_SYSTEM_PROMPT,
    CODE_IDENTIFICATION_USER_PROMPT,
)
from app.modules.llm.prompts.intent_classification_prompt import (
    INTENT_CLASSIFICATION_SYSTEM_PROMPT,
    INTENT_CLASSIFICATION_USER_PROMPT,
)
from app.modules.llm.prompts.query_preprocessing_prompt import (
    QUERY_PREPROCESSING_SYSTEM_PROMPT,
    QUERY_PREPROCESSING_USER_PROMPT,
)

from app.modules.llm.providers.base import BaseLLMProvider
from app.modules.llm.providers.groq_provider import GroqProvider

from app.modules.llm.schemas.llm_schema import IntentClassificationResult
from app.modules.llm.validators.llm_response_validator import (
    validate_intent_classification,
)


class LLMService:
    """
    Service layer for LLM operations.

    The service depends on BaseLLMProvider so that the concrete LLM provider
    can be replaced without changing the service logic.

    GroqProvider is used as the default provider for the current RepoLens
    implementation.
    """

    def __init__(self, provider: BaseLLMProvider | None = None) -> None:
        self.provider = (
            provider
            if provider is not None
            else GroqProvider()
        )

    async def classify_intent(
        self,
        query: str,
    ) -> IntentClassificationResult:
        """
        Classify the user's primary intent.

        The LLM must return:
            - intent
            - parameters
            - confidence

        Classification failures are raised instead of silently falling back
        to ADD_FEATURE. This prevents an incorrect intent from being treated
        as a valid classification.
        """

        if not query or not query.strip():
            raise ValueError(
                "Cannot classify an empty query."
            )

        user_prompt = INTENT_CLASSIFICATION_USER_PROMPT.format(
            query=query.strip(),
        )

        schema = {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": [
                        intent.value
                        for intent in IntentType
                    ],
                },
                "parameters": {
                    "type": "object",
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
            },
            "required": [
                "intent",
                "parameters",
                "confidence",
            ],
            "additionalProperties": False,
        }

        try:
            response = await self.provider.complete_json(
                prompt=user_prompt,
                system_prompt=INTENT_CLASSIFICATION_SYSTEM_PROMPT,
                schema=schema,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Intent classification failed: {exc}"
            ) from exc

        if not isinstance(response, dict):
            raise ValueError(
                "Intent classification returned an invalid response."
            )

        if not validate_intent_classification(response):
            raise ValueError(
                "Intent classification response failed validation."
            )

        raw_intent = response.get("intent")

        try:
            intent = IntentType(raw_intent)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"Invalid intent returned by LLM: {raw_intent!r}"
            ) from exc

        parameters = response.get("parameters")

        if not isinstance(parameters, dict):
            raise ValueError(
                "Intent classification parameters must be an object."
            )

        confidence = response.get("confidence")

        if not isinstance(confidence, (int, float)):
            raise ValueError(
                "Intent classification confidence must be numeric."
            )

        confidence = max(
            0.0,
            min(1.0, float(confidence)),
        )

        return IntentClassificationResult(
            intent=intent,
            parameters=parameters,
            confidence=confidence,
        )

    async def preprocess_query(
        self,
        query: str,
        intent: IntentType | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Extract structured information from the user's query.

        Returns:
            {
                "keywords": [...],
                "identifiers": [...],
                "file_paths": [...],
                "repo_hint": str | None,
                "language_hint": str | None,
            }

        The preprocessing result is normalized but not invented.
        LLM failures are raised so testing can distinguish an actual
        LLM result from a fallback result.
        """

        if not query or not query.strip():
            raise ValueError(
                "Cannot preprocess an empty query."
            )

        user_prompt = QUERY_PREPROCESSING_USER_PROMPT.format(
            query=query.strip(),
            intent=intent.value if intent else "unknown",
            parameters=parameters or {},
        )

        schema = {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "array",
                    "items": {
                        "type": "string",
                    },
                },
                "identifiers": {
                    "type": "array",
                    "items": {
                        "type": "string",
                    },
                },
                "file_paths": {
                    "type": "array",
                    "items": {
                        "type": "string",
                    },
                },
                "repo_hint": {
                    "type": [
                        "string",
                        "null",
                    ],
                },
                "language_hint": {
                    "type": [
                        "string",
                        "null",
                    ],
                },
            },
            "required": [
                "keywords",
                "identifiers",
                "file_paths",
                "repo_hint",
                "language_hint",
            ],
            "additionalProperties": False,
        }

        try:
            response = await self.provider.complete_json(
                prompt=user_prompt,
                system_prompt=QUERY_PREPROCESSING_SYSTEM_PROMPT,
                schema=schema,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Query preprocessing failed: {exc}"
            ) from exc

        if not isinstance(response, dict):
            raise ValueError(
                "Query preprocessing returned an invalid response."
            )

        return {
            "keywords": self._string_list(
                response.get("keywords", [])
            ),
            "identifiers": self._string_list(
                response.get("identifiers", [])
            ),
            "file_paths": self._string_list(
                response.get("file_paths", [])
            ),
            "repo_hint": self._optional_string(
                response.get("repo_hint")
            ),
            "language_hint": self._optional_string(
                response.get("language_hint")
            ),
        }

    async def identify_code_elements(
        self,
        query: str,
        retrieved_chunks: list[dict[str, Any] | str],
    ) -> list[dict[str, Any]]:
        """
        Identify code elements relevant to the query from retrieved chunks.

        Each identified element has the following structure:

        {
            "name": "...",
            "type": "function|class|variable|file|unknown",
            "context": "...",
            "file_path": "..."
        }

        Repository metadata such as file path and line numbers are preserved
        when available.
        """

        if not retrieved_chunks:
            return []

        context_parts: list[str] = []

        for index, chunk in enumerate(
            retrieved_chunks[:10],
            start=1,
        ):
            if isinstance(chunk, dict):
                file_path = chunk.get(
                    "file_path",
                    "unknown",
                )
                start_line = chunk.get(
                    "start_line",
                    "?",
                )
                end_line = chunk.get(
                    "end_line",
                    "?",
                )
                code = (
                    chunk.get("raw_code")
                    or chunk.get("content")
                    or chunk.get("code")
                    or ""
                )

                context_parts.append(
                    f"Snippet {index}: "
                    f"{file_path} "
                    f"(Lines {start_line}-{end_line})\n"
                    f"```\n{code}\n```"
                )

            elif isinstance(chunk, str):
                context_parts.append(
                    f"Snippet {index}:\n"
                    f"```\n{chunk}\n```"
                )

            elif hasattr(chunk, "content"):
                file_path = getattr(chunk, "file_path", "unknown") or "unknown"
                metadata = getattr(chunk, "metadata", {}) or {}
                start_line = metadata.get("start_line", "?")
                end_line = metadata.get("end_line", "?")
                code = getattr(chunk, "content", "") or ""

                context_parts.append(
                    f"Snippet {index}: "
                    f"{file_path} "
                    f"(Lines {start_line}-{end_line})\n"
                    f"```\n{code}\n```"
                )

        if not context_parts:
            return []

        context_text = "\n\n".join(context_parts)

        user_prompt = CODE_IDENTIFICATION_USER_PROMPT.format(
            context=context_text,
            query=query,
        )

        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                    },
                    "type": {
                        "type": "string",
                        "enum": [
                            "function",
                            "class",
                            "variable",
                            "file",
                            "unknown",
                        ],
                    },
                    "context": {
                        "type": "string",
                    },
                    "file_path": {
                        "type": "string",
                    },
                },
                "required": [
                    "name",
                    "type",
                    "context",
                ],
                "additionalProperties": False,
            },
        }

        try:
            response = await self.provider.complete_json(
                prompt=user_prompt,
                system_prompt=CODE_IDENTIFICATION_SYSTEM_PROMPT,
                schema=schema,
            )

            return self._extract_code_elements(response)

        except Exception:
            return []

    async def analyze_code(
        self,
        context: str,
        intent: IntentType,
        prompt: str,
    ) -> dict[str, Any]:
        """
        Analyze retrieved code using the analysis prompt.

        Intent-specific analyzers can build the prompt according to
        the selected intent.
        """

        user_prompt = build_user_prompt(
            intent=intent.value,
            query=prompt,
            context_chunks=[
                {
                    "file_path": "retrieved_context",
                    "start_line": "?",
                    "end_line": "?",
                    "raw_code": context,
                }
            ],
        )

        try:
            response = await self.provider.complete(
                prompt=user_prompt,
                system_prompt=ANALYSIS_SYSTEM_PROMPT,
                max_tokens=2048,
                temperature=0.0,
            )

            return {
                "analysis": response,
                "intent": intent.value,
            }

        except Exception as exc:
            return {
                "analysis": "",
                "intent": intent.value,
                "error": str(exc),
            }

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        """
        Safely normalize an LLM-generated list into list[str].
        """

        if not isinstance(value, list):
            return []

        normalized: list[str] = []
        seen: set[str] = set()

        for item in value:
            if not isinstance(item, str):
                continue

            item = item.strip()

            if not item:
                continue

            key = item.lower()

            if key in seen:
                continue

            seen.add(key)
            normalized.append(item)

        return normalized

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        """
        Safely normalize an optional LLM-generated string.
        """

        if isinstance(value, str) and value.strip():
            return value.strip()

        return None

    @staticmethod
    def _extract_code_elements(
        response: Any,
    ) -> list[dict[str, Any]]:
        """
        Normalize different JSON response shapes into a list of code
        elements.

        The expected response is a JSON array. Some providers/models may
        occasionally wrap the array in an object, so common wrapper keys
        are supported defensively.
        """

        elements: Any = response

        if isinstance(response, dict):
            if "name" in response:
                elements = [response]
            else:
                for key in (
                    "items",
                    "elements",
                    "results",
                    "code_elements",
                ):
                    if isinstance(response.get(key), list):
                        elements = response[key]
                        break

        if not isinstance(elements, list):
            return []

        normalized: list[dict[str, Any]] = []

        allowed_types = {
            "function",
            "class",
            "variable",
            "file",
            "unknown",
        }

        for element in elements:
            if not isinstance(element, dict):
                continue

            name = element.get("name")
            element_type = element.get("type")
            description = element.get("context")

            if not isinstance(name, str) or not name.strip():
                continue

            if not isinstance(element_type, str):
                element_type = "unknown"

            if element_type not in allowed_types:
                element_type = "unknown"

            if not isinstance(description, str):
                description = ""

            normalized_element: dict[str, Any] = {
                "name": name.strip(),
                "type": element_type,
                "context": description.strip(),
            }

            file_path = element.get("file_path")

            if isinstance(file_path, str) and file_path.strip():
                normalized_element["file_path"] = (
                    file_path.strip()
                )

            normalized.append(normalized_element)

        return normalized

