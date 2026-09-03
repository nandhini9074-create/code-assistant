"""
app/modules/search/pipeline/repository_identification.py
Pipeline stage: Repository identification.
"""

from app.core.exceptions import RepositoryNotFoundError
from app.modules.repositories.repository.repository_repo import RepositoryRepository
from app.modules.search.domain.search_domain import SearchContext


class RepositoryIdentificationStage:
    def __init__(self, repo_repo: RepositoryRepository) -> None:
        self.repo_repo = repo_repo

    async def execute(self, context: SearchContext) -> None:
        """Fetch the repository details."""
        repo = await self.repo_repo.get_by_id(context.repo_id)
        if not repo:
            raise RepositoryNotFoundError(f"Repository {context.repo_id} not found")
            
        context.repo_owner = repo.owner
        context.repo_name = repo.name
        context.qdrant_collection = repo.qdrant_collection
