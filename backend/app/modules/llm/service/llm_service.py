"""
app/modules/llm/service/llm_service.py
Service layer for LLM interactions.
"""

from typing import Any

from app.core.enums import IntentType
from app.modules.llm.prompts.intent_classification_prompt import (
    INTENT_CLASSIFICATION_SYSTEM_PROMPT,
    INTENT_CLASSIFICATION_USER_PROMPT,
)
from app.modules.llm.providers.base import BaseLLMProvider
from app.modules.llm.schemas.llm_schema import IntentClassificationResult
from app.modules.llm.validators.llm_response_validator import validate_intent_classification


class LLMService:
    """Service for interacting with LLM providers."""
    
    def __init__(self, provider: BaseLLMProvider) -> None:
        self.provider = provider

    async def classify_intent(self, query: str) -> IntentClassificationResult:
        """Classify the user's intent based on their query."""
        user_prompt = INTENT_CLASSIFICATION_USER_PROMPT.format(query=query)
        
        schema = {
            "type": "object",
            "properties": {
                "intent": {"type": "string"},
                "parameters": {"type": "object"},
                "confidence": {"type": "number"},
            },
            "required": ["intent", "parameters", "confidence"],
        }
        
        response = await self.provider.complete_json(
            prompt=user_prompt,
            system_prompt=INTENT_CLASSIFICATION_SYSTEM_PROMPT,
            schema=schema,
        )
        
        if not validate_intent_classification(response):
            # Fallback for invalid response
            return IntentClassificationResult(
                intent=IntentType.ADD_FEATURE,  # Default fallback
                parameters={"raw_query": query},
                confidence=0.0,
            )
            
        try:
            intent = IntentType(response["intent"])
        except ValueError:
            intent = IntentType.ADD_FEATURE
            
        return IntentClassificationResult(
            intent=intent,
            parameters=response.get("parameters", {}),
            confidence=response.get("confidence", 0.0),
        )

    async def analyze_code(self, context: str, intent: IntentType, prompt: str) -> dict[str, Any]:
        """Analyze code based on the context and intent."""
        # Stub implementation
        return {"analysis": "stub"}

    async def identify_code_elements(self, query: str, retrieved_chunks: list[str]) -> list[dict[str, Any]]:
        """Identify code elements from the query and retrieved chunks."""
        # Stub implementation
        return []
