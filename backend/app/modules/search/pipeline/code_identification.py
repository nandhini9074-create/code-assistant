
"""
app/modules/search/pipeline/code_identification.py

Pipeline stage: Code Identification (Step 7).
"""

from __future__ import annotations

import re
from typing import Any

from app.core.logging import get_logger
from app.modules.llm.service.llm_service import LLMService
from app.modules.search.domain.search_domain import (
    RetrievedChunk,
    SearchContext,
)

logger = get_logger(__name__)

MAX_BROADEN_ATTEMPTS = 2
INITIAL_BROADEN_LIMIT = 20


class CodeIdentificationStage:
    """Identify the target code element from retrieved chunks."""

    def __init__(
        self,
        llm_service: LLMService,
        code_ret_stage=None,
    ) -> None:
        self.llm_service = llm_service
        self.code_ret_stage = code_ret_stage

    async def execute(self, context: SearchContext) -> None:
        if context.early_exit:
            return

        if not context.retrieved_chunks:
            context.early_exit = "EARLY_EXIT_C"
            context.early_exit_message = (
                "Could not identify specific code elements because "
                "no relevant code was retrieved."
            )
            return

        elements = await self._identify(context)

        broaden_attempt = 0

        while (
            not elements
            and broaden_attempt < MAX_BROADEN_ATTEMPTS
        ):
            broaden_attempt += 1

            await self._broaden_retrieval(
                context,
                broaden_attempt,
            )

            if context.retrieved_chunks:
                elements = await self._identify(context)

        if not elements:
            context.early_exit = "EARLY_EXIT_C"
            context.early_exit_message = (
                "Could not identify specific code elements matching "
                "your query after broadened retrieval."
            )
            return

        valid_elements = [
            element
            for element in elements
            if isinstance(element, dict)
            and element.get("name")
        ]

        if not valid_elements:
            context.early_exit = "EARLY_EXIT_C"
            context.early_exit_message = (
                "Code identification returned no valid code elements."
            )
            return

        context.identified_elements = valid_elements

        # Find the best identified element that has an actual
        # matching function/class definition in the retrieved chunks.
        selected_element = self._select_best_element(
            context.retrieved_chunks,
            valid_elements,
        )

        context.target_symbol = selected_element.get("name")

        context.primary_chunk = _find_primary_chunk(
            context.retrieved_chunks,
            selected_element,
        )

        logger.info(
            "code_identification_complete",
            repo_id=context.repo_id,
            elements=len(valid_elements),
            target_symbol=context.target_symbol,
            primary_file=(
                context.primary_chunk.file_path
                if context.primary_chunk
                else None
            ),
        )

    async def _identify(
        self,
        context: SearchContext,
    ) -> list[dict[str, Any]]:
        chunks = context.retrieved_chunks

        if not chunks:
            return []

        try:
            elements = await self.llm_service.identify_code_elements(
                context.query,
                chunks,
            )

            if isinstance(elements, list):
                valid_elements = [
                    element
                    for element in elements
                    if isinstance(element, dict)
                    and element.get("name")
                ]

                if valid_elements:
                    return valid_elements

        except Exception:
            logger.exception(
                "code_identification_llm_failed_using_fallback",
                repo_id=context.repo_id,
            )

        return _fallback_identification(
            context.query,
            chunks,
        )

    async def _broaden_retrieval(
        self,
        context: SearchContext,
        attempt: int,
    ) -> None:
        if self.code_ret_stage is None:
            return

        broader_limit = INITIAL_BROADEN_LIMIT * (2 ** attempt)

        await self.code_ret_stage.execute(
            context,
            limit=broader_limit,
        )

    @staticmethod
    def _select_best_element(
        chunks: list[RetrievedChunk],
        elements: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Prefer the LLM element whose symbol exactly matches
        function/class metadata in the retrieved chunks.
        """

        for element in elements:
            name = str(
                element.get("name", "")
            ).strip().lower()

            if not name:
                continue

            for chunk in chunks:
                metadata = chunk.metadata or {}

                function_name = str(
                    metadata.get("function_name") or ""
                ).strip().lower()

                class_name = str(
                    metadata.get("class_name") or ""
                ).strip().lower()

                if name in {
                    function_name,
                    class_name,
                }:
                    return element

        return elements[0]


def _fallback_identification(
    query: str,
    chunks: list[RetrievedChunk],
) -> list[dict[str, Any]]:
    if not query or not chunks:
        return []

    candidates = re.findall(
        r"\b[A-Za-z_][A-Za-z0-9_]*\b",
        query,
    )

    stop_words = {
        "find",
        "where",
        "is",
        "are",
        "the",
        "a",
        "an",
        "in",
        "on",
        "at",
        "to",
        "from",
        "for",
        "of",
        "and",
        "or",
        "with",
        "used",
        "use",
        "service",
        "class",
        "function",
        "method",
        "code",
    }

    candidates = [
        candidate
        for candidate in candidates
        if candidate.lower() not in stop_words
    ]

    matches: list[dict[str, Any]] = []

    for chunk in chunks:
        metadata = chunk.metadata or {}

        function_name = str(
            metadata.get("function_name") or ""
        ).strip()

        class_name = str(
            metadata.get("class_name") or ""
        ).strip()

        for candidate in candidates:
            candidate_lower = candidate.lower()

            if function_name.lower() == candidate_lower:
                matches.append(
                    {
                        "name": function_name,
                        "file_path": chunk.file_path,
                        "start_line": metadata.get("start_line"),
                        "end_line": metadata.get("end_line"),
                        "chunk_type": metadata.get("chunk_type"),
                        "identification_method": "deterministic_fallback",
                    }
                )
                break

            if class_name.lower() == candidate_lower:
                matches.append(
                    {
                        "name": class_name,
                        "file_path": chunk.file_path,
                        "start_line": metadata.get("start_line"),
                        "end_line": metadata.get("end_line"),
                        "chunk_type": metadata.get("chunk_type"),
                        "identification_method": "deterministic_fallback",
                    }
                )
                break

    unique_matches: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for match in matches:
        key = (
            str(match["name"]).lower(),
            str(match["file_path"]).lower(),
        )

        if key not in seen:
            seen.add(key)
            unique_matches.append(match)

    return unique_matches


def _find_primary_chunk(
    chunks: list[RetrievedChunk],
    element: dict[str, Any],
) -> RetrievedChunk | None:
    """
    Find the primary retrieved chunk for the identified element.

    Priority:
    1. Exact file path + exact function/class symbol.
    2. Exact file path from the LLM identification.
    3. Exact function/class symbol across retrieved chunks.
    4. Highest-scoring retrieved chunk as final fallback.

    The file-path fallback is important when the identified symbol
    is something inside a function, such as a variable, imported
    class, library call, or API usage.

    Example:

        Retrieved chunk:
            file_path = "app.py"
            function_name = "home"

        LLM identifies:
            name = "gTTS"
            file_path = "app.py"

    Since gTTS is not the function_name "home", step 1 will not
    match. Step 2 will still correctly select the app.py chunk.
    """

    if not chunks:
        return None

    name = str(
        element.get("name", "")
    ).strip().lower()

    file_hint = str(
        element.get("file_path", "")
    ).strip().lower()

    # ---------------------------------------------------------
    # 1. Exact file + exact function/class metadata match
    # ---------------------------------------------------------
    if file_hint and name:
        for chunk in chunks:
            chunk_file = str(
                chunk.file_path or ""
            ).strip().lower()

            metadata = chunk.metadata or {}

            function_name = str(
                metadata.get("function_name") or ""
            ).strip().lower()

            class_name = str(
                metadata.get("class_name") or ""
            ).strip().lower()

            if (
                chunk_file == file_hint
                and name in {
                    function_name,
                    class_name,
                }
            ):
                return chunk

    # ---------------------------------------------------------
    # 2. Exact file path match
    #
    # This handles cases where the identified element is inside
    # a function rather than being the function/class itself.
    #
    # Example:
    #     symbol = gTTS
    #     file_path = app.py
    #
    # The retrieved chunk may have:
    #     function_name = home
    #     file_path = app.py
    #
    # Therefore we use the file path to locate the chunk.
    # ---------------------------------------------------------
    if file_hint:
        file_matches = [
            chunk
            for chunk in chunks
            if str(
                chunk.file_path or ""
            ).strip().lower() == file_hint
        ]

        if file_matches:
            return max(
                file_matches,
                key=lambda chunk: chunk.score,
            )

    # ---------------------------------------------------------
    # 3. Exact function/class metadata match
    # ---------------------------------------------------------
    if name:
        matches = []

        for chunk in chunks:
            metadata = chunk.metadata or {}

            function_name = str(
                metadata.get("function_name") or ""
            ).strip().lower()

            class_name = str(
                metadata.get("class_name") or ""
            ).strip().lower()

            if name in {
                function_name,
                class_name,
            }:
                matches.append(chunk)

        if matches:
            return max(
                matches,
                key=lambda chunk: chunk.score,
            )

    # ---------------------------------------------------------
    # 4. Final fallback:
    # Use the highest-scoring retrieved chunk.
    #
    # This guarantees that primary_chunk is still populated
    # whenever retrieval returned at least one chunk.
    # ---------------------------------------------------------
    return max(
        chunks,
        key=lambda chunk: chunk.score,
    )
