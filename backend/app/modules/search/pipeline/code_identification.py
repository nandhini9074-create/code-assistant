
"""
app/modules/search/pipeline/code_identification.py

Pipeline stage: Code Identification (Step 7).

Identifies target code elements from retrieved chunks using the LLM.

If LLM identification fails, a deterministic fallback searches the
retrieved code directly for symbols/terms from the user query.

If identification still fails, retrieval is broadened up to
MAX_BROADEN_ATTEMPTS times.

If no valid code elements can be identified after all attempts,
Early Exit C is triggered.
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
    """Pipeline stage responsible for identifying target code elements."""

    def __init__(
        self,
        llm_service: LLMService,
        code_ret_stage=None,
    ) -> None:
        """
        Initialize the code identification stage.

        Args:
            llm_service: Service used to identify code elements.
            code_ret_stage: Optional CodeRetrievalStage used to broaden
                retrieval when identification fails.
        """

        self.llm_service = llm_service
        self.code_ret_stage = code_ret_stage

    async def execute(self, context: SearchContext) -> None:
        """
        Identify target code elements from retrieved chunks.

        Strategy:
        1. Try LLM-based identification.
        2. If LLM identification fails, use deterministic matching
           against the retrieved code.
        3. If still unsuccessful, broaden retrieval.
        4. After all attempts fail, trigger Early Exit C.
        """

        if context.early_exit:
            logger.info(
                "code_identification_skipped",
                reason=context.early_exit,
                repo_id=context.repo_id,
            )
            return

        if not context.retrieved_chunks:
            logger.warning(
                "code_identification_no_retrieved_chunks",
                repo_id=context.repo_id,
            )

            context.early_exit = "EARLY_EXIT_C"
            context.early_exit_message = (
                "Could not identify specific code elements because "
                "no relevant code was retrieved."
            )
            return

        # -----------------------------------------------------------
        # First identification attempt
        # -----------------------------------------------------------

        elements = await self._identify(context)

        broaden_attempt = 0

        # -----------------------------------------------------------
        # Broaden retrieval if identification failed
        # -----------------------------------------------------------

        while (
            not elements
            and broaden_attempt < MAX_BROADEN_ATTEMPTS
        ):
            broaden_attempt += 1

            logger.info(
                "code_identification_broadening",
                attempt=broaden_attempt,
                repo_id=context.repo_id,
            )

            await self._broaden_retrieval(
                context,
                attempt=broaden_attempt,
            )

            if not context.retrieved_chunks:
                logger.warning(
                    "code_identification_broadening_no_results",
                    attempt=broaden_attempt,
                    repo_id=context.repo_id,
                )
                continue

            elements = await self._identify(context)

        # -----------------------------------------------------------
        # Identification failed completely
        # -----------------------------------------------------------

        if not elements:
            logger.warning(
                "code_identification_failed",
                repo_id=context.repo_id,
                query=context.query,
            )

            context.early_exit = "EARLY_EXIT_C"
            context.early_exit_message = (
                "Could not identify specific code elements matching "
                "your query after broadened retrieval."
            )
            return

        # -----------------------------------------------------------
        # Validate returned elements
        # -----------------------------------------------------------

        valid_elements = [
            element
            for element in elements
            if isinstance(element, dict)
            and element.get("name")
        ]

        if not valid_elements:
            logger.warning(
                "code_identification_invalid_elements",
                repo_id=context.repo_id,
            )

            context.early_exit = "EARLY_EXIT_C"
            context.early_exit_message = (
                "Code identification returned no valid code elements."
            )
            return

        context.identified_elements = valid_elements

        # -----------------------------------------------------------
        # Primary target
        # -----------------------------------------------------------

        first_element = valid_elements[0]

        context.target_symbol = first_element.get("name")

        # -----------------------------------------------------------
        # Find supporting retrieved chunk
        # -----------------------------------------------------------

        primary_chunk = _find_primary_chunk(
            context.retrieved_chunks,
            first_element,
        )

        if primary_chunk is not None:
            context.primary_chunk = primary_chunk

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
        """
        Identify code elements from retrieved evidence.

        The LLM is preferred.

        If the LLM fails because of structured-output/JSON issues,
        deterministic matching is used as a fallback so that an
        otherwise valid retrieved chunk is not discarded.
        """

        # Use the complete retrieved candidates configuration
        chunks = context.retrieved_chunks

        if not chunks:
            return []

        # -----------------------------------------------------------
        # LLM identification
        # -----------------------------------------------------------

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
                    logger.info(
                        "code_identification_llm_success",
                        repo_id=context.repo_id,
                        elements=len(valid_elements),
                    )

                    return valid_elements

                logger.warning(
                    "code_identification_llm_returned_no_valid_elements",
                    repo_id=context.repo_id,
                )

        except Exception:
            logger.exception(
                "code_identification_llm_failed_using_fallback",
                repo_id=context.repo_id,
            )

        # -----------------------------------------------------------
        # Deterministic fallback
        # -----------------------------------------------------------

        fallback_elements = _fallback_identification(
            context.query,
            chunks,
        )

        if fallback_elements:
            logger.info(
                "code_identification_fallback_success",
                repo_id=context.repo_id,
                elements=len(fallback_elements),
            )

            return fallback_elements

        return []

    async def _broaden_retrieval(
        self,
        context: SearchContext,
        attempt: int,
    ) -> None:
        """
        Re-run code retrieval with an expanded result limit.

        attempt 1 -> 40
        attempt 2 -> 80
        """

        if self.code_ret_stage is None:
            logger.warning(
                "code_identification_broadening_unavailable",
                repo_id=context.repo_id,
            )
            return

        broader_limit = INITIAL_BROADEN_LIMIT * (2 ** attempt)

        logger.info(
            "code_retrieval_broadened",
            repo_id=context.repo_id,
            attempt=attempt,
            limit=broader_limit,
        )

        await self.code_ret_stage.execute(
            context,
            limit=broader_limit,
        )


def _fallback_identification(
    query: str,
    chunks: list[RetrievedChunk],
) -> list[dict[str, Any]]:
    """
    Deterministically identify a code element from retrieved chunks.

    This fallback is intentionally conservative.

    It looks for:
    - PascalCase identifiers
    - camelCase identifiers
    - identifiers explicitly present in the query

    The element is returned only when the identifier actually occurs
    in the retrieved code.
    """

    if not query or not chunks:
        return []

    # ---------------------------------------------------------------
    # Extract likely code identifiers from the query.
    #
    # Examples:
    #
    # PayoutTransactionService
    # payoutTransactionService
    # TransactionController
    # ---------------------------------------------------------------

    candidates = re.findall(
        r"\b[A-Za-z_][A-Za-z0-9_]*\b",
        query,
    )

    # Remove common natural-language words.
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
        "injected",
        "injection",
        "inject",
        "dependency",
        "dependencies",
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

    # Prefer identifiers that look like actual code symbols.
    symbol_candidates = [
        candidate
        for candidate in candidates
        if (
            any(char.isupper() for char in candidate[1:])
            or "_" in candidate
        )
    ]

    if not symbol_candidates:
        symbol_candidates = candidates

    # ---------------------------------------------------------------
    # Search retrieved chunks
    # ---------------------------------------------------------------

    matches: list[dict[str, Any]] = []

    for chunk in chunks:
        code = getattr(chunk, "content", "") or ""

        if not code:
            continue

        code_lower = code.lower()

        for candidate in symbol_candidates:
            if candidate.lower() not in code_lower:
                continue

            matches.append(
                {
                    "name": candidate,
                    "file_path": chunk.file_path,
                    "start_line": (
                        chunk.metadata.get("start_line")
                        if chunk.metadata
                        else getattr(chunk, "start_line", None)
                    ),
                    "end_line": (
                        chunk.metadata.get("end_line")
                        if chunk.metadata
                        else getattr(chunk, "end_line", None)
                    ),
                    "chunk_type": (
                        chunk.metadata.get("chunk_type")
                        if chunk.metadata
                        else getattr(chunk, "chunk_type", None)
                    ),
                    "identification_method": "deterministic_fallback",
                }
            )

            # One strong symbol per chunk is enough.
            break

    # Remove duplicates.
    unique_matches: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for match in matches:
        key = (
            str(match.get("name", "")).lower(),
            str(match.get("file_path", "")).lower(),
        )

        if key in seen:
            continue

        seen.add(key)
        unique_matches.append(match)

    return unique_matches


def _find_primary_chunk(
    chunks: list[RetrievedChunk],
    element: dict[str, Any],
) -> RetrievedChunk | None:
    """
    Find the retrieved chunk that best supports the identified element.

    Matching priority:
    1. Exact file-path hint.
    2. Relative/path-fragment hint.
    3. Symbol/name found in chunk content.
    4. Highest-scored retrieved chunk.
    """

    if not chunks:
        return None

    name = str(
        element.get("name", "")
    ).strip().lower()

    file_hint = str(
        element.get("file_path", "")
    ).strip().lower()

    # ---------------------------------------------------------------
    # 1. Exact file-path match
    # ---------------------------------------------------------------

    if file_hint:
        for chunk in chunks:
            if chunk.file_path.lower() == file_hint:
                return chunk

        # -----------------------------------------------------------
        # 2. Relative/path-fragment match
        # -----------------------------------------------------------

        for chunk in chunks:
            chunk_path = chunk.file_path.lower()

            if (
                file_hint in chunk_path
                or chunk_path in file_hint
            ):
                return chunk

    # ---------------------------------------------------------------
    # 3. Symbol/name in actual code
    # ---------------------------------------------------------------

    if name:
        for chunk in chunks:
            content = getattr(chunk, "content", "") or ""

            if name in content.lower():
                return chunk

    # ---------------------------------------------------------------
    # 4. Highest retrieval score
    # ---------------------------------------------------------------

    return max(
        chunks,
        key=lambda chunk: chunk.score,
    )

