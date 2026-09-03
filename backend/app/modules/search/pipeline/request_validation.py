"""
app/modules/search/pipeline/request_validation.py
Pipeline stage: Validate search request.
"""

from app.core.exceptions import ValidationError
from app.modules.search.domain.search_domain import SearchContext


class RequestValidationStage:
    async def execute(self, context: SearchContext) -> None:
        """Validate request payload."""
        if not context.repo_id:
            raise ValidationError("repo_id is required")
        if not context.query or len(context.query) < 3:
            raise ValidationError("query must be at least 3 characters")
