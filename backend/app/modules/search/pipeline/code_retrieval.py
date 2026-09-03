"""
app/modules/search/pipeline/code_retrieval.py
Pipeline stage: Code retrieval.
"""

from app.modules.search.domain.search_domain import SearchContext
from app.modules.search.retrieval.hybrid_search import HybridSearch


class CodeRetrievalStage:
    def __init__(self, hybrid_search: HybridSearch) -> None:
        self.hybrid_search = hybrid_search

    async def execute(self, context: SearchContext) -> None:
        """Perform hybrid search to retrieve relevant code chunks."""
        # Note: Embedding the query happens inside or just before hybrid search.
        # We stub the query vector here for simplicity,
        # but in a real system we'd call the LLM/embedding provider.
        if not context.query_vector:
            context.query_vector = [0.0] * 1024
            
        chunks = await self.hybrid_search.search(context, limit=20)
        context.retrieved_chunks = chunks
