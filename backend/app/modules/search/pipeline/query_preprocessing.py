"""
app/modules/search/pipeline/query_preprocessing.py
Pipeline stage: Query preprocessing.
"""

from app.modules.llm.service.llm_service import LLMService
from app.modules.search.domain.search_domain import SearchContext


class QueryPreprocessingStage:
    def __init__(self, llm_service: LLMService) -> None:
        self.llm_service = llm_service

    async def execute(self, context: SearchContext) -> None:
        """Extract keywords, identifiers, and file paths from the query."""
        # For stub purposes, just split the query on spaces
        parts = context.query.split()
        context.keywords = parts
        
        # We would normally use LLMService or a dedicated extraction method
        # elements = await self.llm_service.extract_elements(context.query)
        # context.identifiers = elements.identifiers
        # context.file_paths = elements.file_paths
