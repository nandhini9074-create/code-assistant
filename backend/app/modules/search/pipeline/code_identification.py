
"""
app/modules/search/pipeline/code_identification.py

Pipeline stage: Code Identification (Step 7).

Identifies target code elements from retrieved chunks using the LLM.
If identification fails, retrieval is broadened up to
MAX_BROADEN_ATTEMPTS times.

If no valid code elements can be identified after all attempts,
Early Exit C is triggered.
"""

from __future__ import annotations

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

        If identification returns no elements, retrieval is broadened
        up to MAX_BROADEN_ATTEMPTS times.

        If identification still fails, Early Exit C is triggered.
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

        elements = await self._identify(context)

        broaden_attempt = 0

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

        # Keep only valid dictionary elements.
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

        # The first identified element is the primary target.
        first_element = valid_elements[0]

        context.target_symbol = first_element.get("name")

        # Locate the retrieved chunk that best supports the
        # identified element.
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

        The LLM must identify elements only from the retrieved
        repository context. It must not invent symbols or files.
        """

        chunks = context.retrieved_chunks[:10]

        if not chunks:
            return []

        try:
            elements = await self.llm_service.identify_code_elements(
                context.query,
                chunks,
            )
        except Exception:
            logger.exception(
                "code_identification_llm_failed",
                repo_id=context.repo_id,
            )
            return []

        if not isinstance(elements, list):
            logger.warning(
                "code_identification_invalid_llm_response",
                repo_id=context.repo_id,
            )
            return []

        return [
            element
            for element in elements
            if isinstance(element, dict)
        ]

    async def _broaden_retrieval(
        self,
        context: SearchContext,
        attempt: int,
    ) -> None:
        """
        Re-run code retrieval with an expanded result limit.

        Each retry doubles the previous broadening limit:
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


def _find_primary_chunk(
    chunks: list[RetrievedChunk],
    element: dict[str, Any],
) -> RetrievedChunk | None:
    """
    Find the retrieved chunk that best supports the identified element.

    Matching priority:
    1. Exact file-path hint.
    2. Symbol/name found in chunk content.
    3. Highest-scored retrieved chunk.
    """

    if not chunks:
        return None

    name = str(element.get("name", "")).strip().lower()
    file_hint = str(element.get("file_path", "")).strip().lower()

    # Prefer an explicit file-path match.
    if file_hint:
        for chunk in chunks:
            if chunk.file_path.lower() == file_hint:
                return chunk

        # Also support a relative/path-fragment hint.
        for chunk in chunks:
            if (
                file_hint in chunk.file_path.lower()
                or chunk.file_path.lower() in file_hint
            ):
                return chunk

    # Then look for the identified symbol in the actual
    # retrieved code content.
    if name:
        for chunk in chunks:
            if name in chunk.content.lower():
                return chunk

    # Final fallback: highest retrieval score.
    return max(chunks, key=lambda chunk: chunk.score)

