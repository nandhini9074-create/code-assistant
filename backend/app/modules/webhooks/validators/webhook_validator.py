"""
app/modules/webhooks/validators/webhook_validator.py
Validators for GitHub webhooks.
"""

from typing import Any

from app.core.exceptions import ValidationError
from app.modules.repositories.repository.repository_repo import RepositoryRepository


from app.core.logging import get_logger

logger = get_logger(__name__)

class WebhookValidator:
    def __init__(self, repo_repo: RepositoryRepository) -> None:
        self.repo_repo = repo_repo

    async def validate_push_event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate event type, branch, and repo registration."""
        logger.debug("validating_webhook_event", event_type=event_type)
        if event_type != "push":
            logger.warning("webhook_validation_failed", reason="unsupported_event_type", event_type=event_type)
            raise ValidationError(f"Unsupported event type: {event_type}")

        ref = payload.get("ref", "")
        if not ref.startswith("refs/heads/"):
            logger.warning("webhook_validation_failed", reason="not_a_branch_push", ref=ref)
            raise ValidationError("Not a push to a branch")
            
        branch = ref.removeprefix("refs/heads/")
        
        repository = payload.get("repository", {})
        repo_name = repository.get("full_name")
        if not repo_name:
            logger.warning("webhook_validation_failed", reason="missing_repository_name")
            raise ValidationError("Repository full_name not found in payload")
            
        # Get repo using get_by_full_name
        target_repo = await self.repo_repo.get_by_full_name(repo_name)
        
        if not target_repo:
            logger.warning("webhook_validation_failed", reason="repo_not_registered", repo_name=repo_name)
            raise ValidationError(f"Repository {repo_name} not registered")
            
        if target_repo.default_branch != branch:
            logger.warning("webhook_validation_failed", reason="wrong_branch", expected=target_repo.default_branch, received=branch, repo_name=repo_name)
            raise ValidationError(f"Repository {repo_name} (branch: {branch}) not registered or not default branch")
            
        logger.info("webhook_validation_passed", repo_name=repo_name, branch=branch)
        return {"repo": target_repo, "branch": branch}
