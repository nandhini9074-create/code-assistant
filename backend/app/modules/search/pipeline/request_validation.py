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

        if not context.repo_name or not context.repo_name.strip():
            raise ValidationError(
                "repo_name is required"
            )

        if not context.query or not context.query.strip():
            raise ValidationError(
                "query is required"
            )

        query = context.query.strip()

        if len(query) < 3:
            raise ValidationError(
                "query must be at least 3 characters"
            )

        if len(query) > MAX_QUERY_LENGTH:
            raise ValidationError(
                f"query must not exceed {MAX_QUERY_LENGTH} characters"
            )