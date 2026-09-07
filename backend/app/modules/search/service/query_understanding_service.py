
"""
app/modules/search/service/query_understanding_service.py

Service for the initial query-understanding pipeline.

Current scope:
1. Request validation
2. Intent classification
3. Query preprocessing

This service intentionally does not access:
- PostgreSQL
- Qdrant
- repository data
- embeddings
- code retrieval
- code analysis
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.modules.search.domain.search_domain import SearchContext
from app.modules.search.pipeline.intent_classification import IntentClassificationStage
from app.modules.search.pipeline.query_preprocessing import QueryPreprocessingStage
from app.modules.search.pipeline.request_validation import RequestValidationStage
from app.modules.search.schemas.search_schema import QueryUnderstandingResponse

logger = get_logger(__name__)


class QueryUnderstandingService:
    """Runs only the initial query-understanding stages."""

    def __init__(
        self,
        val_stage: RequestValidationStage,
        intent_stage: IntentClassificationStage,
        query_prep_stage: QueryPreprocessingStage,
    ) -> None:
        self.val_stage = val_stage
        self.intent_stage = intent_stage
        self.query_prep_stage = query_prep_stage

    async def understand(
        self,
        repo_id: str,
        query: str,
    ) -> QueryUnderstandingResponse:
        """Validate, classify intent, and preprocess the user's query."""

        context = SearchContext(
            repo_id=repo_id,
            query=query,
        )

        try:
            # Stage 1: Request Validation
            await self.val_stage.execute(context)

            # Stage 2: Intent Classification
            await self.intent_stage.execute(context)

            # Stage 3: Query Preprocessing
            await self.query_prep_stage.execute(context)

            return QueryUnderstandingResponse(
                success=True,
                query=context.query,
                intent=(
                    context.intent.value
                    if context.intent is not None
                    else None
                ),
                parameters=context.intent_parameters,
                confidence=None,
                keywords=context.keywords,
                identifiers=context.identifiers,
                file_paths=context.file_paths,
                repo_hint=context.repo_hint,
                language_hint=context.language_hint,
            )

        except Exception as exc:
            logger.error(
                "query_understanding_failed",
                repo_id=repo_id,
                exc_info=exc,
            )

            return QueryUnderstandingResponse(
                success=False,
                query=query,
                error=str(exc),
            )

