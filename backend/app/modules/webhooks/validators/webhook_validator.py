"""
app/modules/webhooks/validators/webhook_validator.py
Validators for GitHub webhooks.
"""

from typing import Any

from app.core.exceptions import ValidationError
from app.modules.repositories.repository.repository_repo import RepositoryRepository


class WebhookValidator:
    def __init__(self, repo_repo: RepositoryRepository) -> None:
        self.repo_repo = repo_repo

    async def validate_push_event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate event type, branch, and repo registration."""
        if event_type != "push":
            raise ValidationError(f"Unsupported event type: {event_type}")

        ref = payload.get("ref", "")
        if not ref.startswith("refs/heads/"):
            raise ValidationError("Not a push to a branch")
            
        branch = ref.removeprefix("refs/heads/")
        
        repository = payload.get("repository", {})
        repo_name = repository.get("full_name")
        if not repo_name:
            raise ValidationError("Repository full_name not found in payload")
            
        # Get all repos to find one matching this name and branch
        # In a real system, we'd query by owner/name/branch.
        # Here we just iterate to find a matching active repo.
        repos = await self.repo_repo.list_all()
        target_repo = None
        for repo in repos:
            if f"{repo.owner}/{repo.name}" == repo_name and repo.default_branch == branch:
                target_repo = repo
                break
                
        if not target_repo:
            raise ValidationError(f"Repository {repo_name} (branch: {branch}) not registered")
            
        return {"repo": target_repo, "branch": branch}
