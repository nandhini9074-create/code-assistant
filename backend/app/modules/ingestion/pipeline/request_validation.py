"""
app/modules/ingestion/pipeline/request_validation.py
Pipeline stage: Validate ingestion request.
"""

from app.core.exceptions import ValidationError
from app.modules.ingestion.domain.ingestion_domain import IngestionContext
from app.modules.repositories.repository.repository_repo import RepositoryRepository


class RequestValidationStage:
    def __init__(self, repo_repo: RepositoryRepository) -> None:
        self.repo_repo = repo_repo

    async def execute(self, context: IngestionContext) -> None:
        """Validates that the repository exists before processing."""
        repo = await self.repo_repo.get_by_id(context.repo_id)
        if not repo:
            raise ValidationError(f"Repository {context.repo_id} not found.")
