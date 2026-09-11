
"""
app/modules/search/pipeline/query_preprocessing.py

Pipeline stage: Query preprocessing / structured query understanding.

Extracts structured information from the user's query after intent
classification.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.modules.llm.service.llm_service import LLMService
from app.modules.search.domain.search_domain import SearchContext

logger = get_logger(__name__)


class QueryPreprocessingStage:
    """Pipeline stage responsible for structured query preprocessing."""

    def __init__(self, llm_service: LLMService) -> None:
        self.llm_service = llm_service

    async def execute(self, context: SearchContext) -> None:
        """
        Extract structured query information using the LLM.

        The stage stores only information returned by LLMService:
        - keywords
        - identifiers
        - file paths
        - repository hint
        - language hint

        LLM failures are propagated instead of silently falling back
        to heuristic keyword extraction.
        """

        if context.early_exit:
            logger.info(
                "query_preprocessing_skipped",
                reason=context.early_exit,
                repo_id=context.repo_id,
            )
            return

        if not context.query or not context.query.strip():
            raise ValueError(
                "Cannot preprocess an empty query."
            )

        if context.intent is None:
            raise ValueError(
                "Cannot preprocess query before intent classification."
            )

        result = await self.llm_service.preprocess_query(
            query=context.query,
            intent=context.intent,
            parameters=context.intent_parameters,
        )

        if not isinstance(result, dict):
            raise ValueError(
                "Query preprocessing returned an invalid result."
            )

        context.keywords = result.get("keywords", [])
        context.identifiers = result.get("identifiers", [])
        context.file_paths = result.get("file_paths", [])
        context.repo_hint = result.get("repo_hint")
        context.language_hint = result.get("language_hint")

        logger.info(
            "query_preprocessing_complete",
            repo_id=context.repo_id,
            keywords=context.keywords,
            identifiers=context.identifiers,
            file_paths=context.file_paths,
            repo_hint=context.repo_hint,
            language_hint=context.language_hint,
        )

