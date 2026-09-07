"""
app/modules/search/pipeline/repository_identification.py
Pipeline stage: Repository identification (Step 4).

Resolution order:
  1. Direct UUID lookup via context.repo_id (always tried first).
  2. Hint lookup via context.repo_hint (owner/repo from query preprocessing).
  3. Intent-parameter lookup via intent_parameters["repo"] / intent_parameters["repository"].
  4. If all fail → Early Exit A (structured, not an unhandled exception).
"""

from app.core.logging import get_logger
from app.modules.repositories.repository.repository_repo import RepositoryRepository
from app.modules.search.domain.search_domain import SearchContext

logger = get_logger(__name__)


class RepositoryIdentificationStage:
    def __init__(self, repo_repo: RepositoryRepository) -> None:
        self.repo_repo = repo_repo

    async def execute(self, context: SearchContext) -> None:
        """Resolve the repository; set Early Exit A if unresolvable."""
        repo = None

        # 1. Direct ID lookup (primary path when repo_id is supplied)
        if context.repo_id:
            repo = await self.repo_repo.get_by_id(context.repo_id)

        # 2. Hint from query preprocessing: "owner/repo"
        if repo is None and context.repo_hint:
            repo = await self.repo_repo.get_by_full_name(context.repo_hint)

        # 3. Intent-parameter hints
        if repo is None:
            for key in ("repo", "repository", "full_name"):
                candidate = context.intent_parameters.get(key)
                if candidate and isinstance(candidate, str):
                    repo = await self.repo_repo.get_by_full_name(candidate)
                    if repo:
                        break

        # 4. Unresolvable → Early Exit A
        if repo is None:
            identifier = context.repo_id or context.repo_hint or "unknown"
            logger.warning("repository_not_found", identifier=identifier)
            context.early_exit = "EARLY_EXIT_A"
            context.early_exit_message = (
                f"Repository '{identifier}' could not be found. "
                "Please clarify which repository should be analysed."
            )
            return

        context.repo_owner = repo.owner
        context.repo_name = repo.name
        context.qdrant_collection = repo.qdrant_collection

        logger.info(
            "repository_identified",
            repo_id=str(repo.id),
            full_name=repo.full_name,
            collection=repo.qdrant_collection,
        )
