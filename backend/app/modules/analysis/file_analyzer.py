"""
app/modules/analysis/file_analyzer.py
Business logic for executing code analysis using LLMs.
"""

from __future__ import annotations

from typing import Any

from app.core.exceptions import LLMError
from app.core.logging import get_logger
from app.modules.analysis.schemas import INTENT_ANALYSIS_SCHEMA
from app.modules.llm.prompts.analysis_prompt import (
    ANALYSIS_SYSTEM_PROMPT,
    build_user_prompt,
)
from app.modules.llm.service.llm_service import generate_structured

logger = get_logger(__name__)


async def analyze_chunks_for_intent(
    intent: str,
    query: str,
    chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Perform a structured analysis of retrieved code chunks against a specific user intent.
    
    Args:
        intent: The high-level intent (e.g., 'FIND_SECURITY_VULNERABILITY').
        query: The specific user query (e.g., 'Where is the auth token validated?').
        chunks: List of context chunks retrieved from Qdrant. Each chunk should 
                contain at least 'file_path', 'start_line', 'end_line', and 'raw_code'.
                
    Returns:
        A dictionary matching the INTENT_ANALYSIS_SCHEMA.
    """
    logger.info(
        "analyzing_chunks_for_intent", 
        intent=intent, 
        chunk_count=len(chunks)
    )
    
    user_prompt = build_user_prompt(
        intent=intent, 
        query=query, 
        context_chunks=chunks,
    )
    
    try:
        # Request a structured JSON response from the LLM
        result = await generate_structured(
            system_prompt=ANALYSIS_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            schema=INTENT_ANALYSIS_SCHEMA,
            temperature=0.2,  # Low temperature for more analytical/factual output
        )
        return result
        
    except LLMError as exc:
        logger.error("intent_analysis_failed", exc_info=exc)
        # Return a graceful fallback response if the LLM fails
        return {
            "summary": f"Analysis failed due to an LLM error: {exc}",
            "key_findings": [],
            "files_referenced": [],
            "confidence_score": 0.0,
        }
    except Exception as exc:
        logger.error("intent_analysis_unexpected_error", exc_info=exc)
        return {
            "summary": "An unexpected error occurred during analysis.",
            "key_findings": [],
            "files_referenced": [],
            "confidence_score": 0.0,
        }
