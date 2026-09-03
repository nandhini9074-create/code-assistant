"""
app/modules/search/pipeline/code_identification.py
Pipeline stage: Code identification.
"""

from app.modules.llm.service.llm_service import LLMService
from app.modules.search.domain.search_domain import SearchContext


class CodeIdentificationStage:
    def __init__(self, llm_service: LLMService) -> None:
        self.llm_service = llm_service

    async def execute(self, context: SearchContext) -> None:
        """Use LLM to identify relevant code elements from retrieved chunks."""
        if not context.retrieved_chunks:
            return
            
        chunk_texts = [f"File: {c.file_path}\n{c.content}" for c in context.retrieved_chunks[:5]]
        
        elements = await self.llm_service.identify_code_elements(context.query, chunk_texts)
        context.identified_elements = elements
