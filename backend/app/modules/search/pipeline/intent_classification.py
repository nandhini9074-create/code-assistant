"""
app/modules/search/pipeline/intent_classification.py
Pipeline stage: Classify search intent.
"""

from app.modules.llm.service.llm_service import LLMService
from app.modules.search.domain.search_domain import SearchContext


class IntentClassificationStage:
    def __init__(self, llm_service: LLMService) -> None:
        self.llm_service = llm_service

    async def execute(self, context: SearchContext) -> None:
        """Use LLM to determine intent and extract parameters."""
        result = await self.llm_service.classify_intent(context.query)
        context.intent = result.intent
        context.intent_parameters = result.parameters
