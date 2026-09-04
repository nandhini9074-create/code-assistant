"""
app/modules/ingestion/pipeline/request_validation.py
Pipeline stage: Validate ingestion request.
"""

import uuid

from app.core.exceptions import ValidationError
from app.core.logging import get_logger
from app.modules.ingestion.domain.ingestion_domain import IngestionContext
from app.modules.repositories.repository.repository_repo import RepositoryRepository

logger = get_logger(__name__)


class RequestValidationStage:
    def __init__(self, repo_repo: RepositoryRepository) -> None:
        self.repo_repo = repo_repo

    async def execute(self, context: IngestionContext) -> None:
        """Validates that the repository exists before processing."""
        logger.info("stage_1_request_validation_started", repo_id=context.repo_id, job_id=context.job_id)
        repo = await self.repo_repo.get_by_id(uuid.UUID(context.repo_id))
        if not repo:
            logger.error("stage_1_request_validation_failed", repo_id=context.repo_id, reason="Repository not found in DB")
            raise ValidationError(f"Repository {context.repo_id} not found.")
        logger.info("stage_1_request_validation_passed", repo_id=context.repo_id, repo_name=repo.name)
