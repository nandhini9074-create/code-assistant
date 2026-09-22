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
        github_repo_id = repository.get("id")
        
        if not repo_name:
            logger.warning("webhook_validation_failed", reason="missing_repository_name")
            raise ValidationError("Repository full_name not found in payload")
            
        target_repo = None
        if github_repo_id:
            target_repo = await self.repo_repo.get_by_github_id(github_repo_id)
            if target_repo and target_repo.full_name != repo_name:
                logger.info("repository_rename_detected", old_name=target_repo.full_name, new_name=repo_name, github_repo_id=github_repo_id)
                new_repo_name = repo_name.split("/")[-1]
                new_repo_url = repository.get("html_url", target_repo.repo_url)
                
                await self.repo_repo.update_fields(
                    target_repo.id, 
                    {"repo_name": new_repo_name, "repo_url": new_repo_url}
                )
                target_repo = await self.repo_repo.get_by_id(target_repo.id)
                
        if not target_repo:
            # Fallback to get_by_full_name for legacy repos missing github_repo_id
            target_repo = await self.repo_repo.get_by_full_name(repo_name)
        
        if not target_repo:
            logger.warning("webhook_validation_failed", reason="repo_not_registered", repo_name=repo_name)
            raise ValidationError(f"Repository {repo_name} not registered")
            
        if target_repo.default_branch != branch:
            logger.warning("webhook_validation_failed", reason="wrong_branch", expected=target_repo.default_branch, received=branch, repo_name=repo_name)
            raise ValidationError(f"Repository {repo_name} (branch: {branch}) not registered or not default branch")
            
        logger.info("webhook_validation_passed", repo_name=repo_name, branch=branch)
        return {"repo": target_repo, "branch": branch}
