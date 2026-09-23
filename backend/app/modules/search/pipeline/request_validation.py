"""
app/modules/search/pipeline/request_validation.py

Pipeline stage: Request Validation (Step 1).

Validates the minimum information required to start a repository
search request.
"""

from __future__ import annotations

from app.core.exceptions import ValidationError
from app.modules.search.domain.search_domain import SearchContext


MAX_QUERY_LENGTH = 10_000


class RequestValidationStage:
    """Validate the incoming search request."""

    async def execute(self, context: SearchContext) -> None:
        """Validate the minimum required search request fields."""

        has_source = bool(
            context.source_type
            and context.source_location
            and context.source_location.strip()
        )
        has_legacy_repository = bool(
            context.repo_name and context.repo_name.strip()
        )

        if not has_source and not has_legacy_repository:
            raise ValidationError(
                "source is required"
            )

        if not context.query or not context.query.strip():
            raise ValidationError(
                "query is required"
            )

        query = context.query.strip()

        if len(query) < 1:
            raise ValidationError(
                "query must be at least 1 character"
            )

        if len(query) > MAX_QUERY_LENGTH:
            raise ValidationError(
                f"query must not exceed {MAX_QUERY_LENGTH} characters"
            )