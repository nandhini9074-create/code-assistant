"""
app/modules/search/pipeline/response_generation.py
Pipeline stage: Response generation.
"""

from app.modules.llm.service.llm_service import LLMService
from app.modules.search.domain.search_domain import SearchContext
from app.modules.search.schemas.search_schema import EvidenceItem, SearchResponse


class ResponseGenerationStage:
    def __init__(self, llm_service: LLMService) -> None:
        self.llm_service = llm_service

    async def execute(self, context: SearchContext) -> None:
        """Generate final response using LLM."""
        if context.insufficient_evidence:
            context.final_response = SearchResponse(
                intent=context.intent.value if context.intent else "unknown",
                analysis={"message": "insufficient_evidence"},
                evidence=[],
            )
            return

        # Use LLM to analyze the code based on the context and intent
        # In a real system, this would call specific analyzers based on context.intent
        analysis = await self.llm_service.analyze_code(
            context=context.llm_context or "",
            intent=context.intent, # type: ignore
            prompt=context.query,
        )

        evidence_items = [
            EvidenceItem(
                file_path=chunk.file_path,
                snippet=chunk.content[:200] + "...",
                score=chunk.score,
            )
            for chunk in context.retrieved_chunks
        ]

        context.final_response = SearchResponse(
            intent=context.intent.value if context.intent else "unknown",
            analysis=analysis,
            evidence=evidence_items,
        )
