"""
app/modules/code_analysis/analyzers/fix_bug_analyzer.py
Analyzer for FIX_BUG intent.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.modules.code_analysis.analyzers.base_analyzer import BaseAnalyzer
from app.modules.code_analysis.domain.analysis_domain import AnalysisResult, ValidationResult
from app.modules.code_analysis.prompts.fix_bug_prompt import (
    FIX_BUG_SYSTEM_PROMPT,
    FIX_BUG_USER_PROMPT,
)
from app.modules.llm.service.llm_service import LLMService
from app.modules.search.domain.search_domain import SearchContext

logger = get_logger(__name__)

_SCHEMA = {
    "type": "object",
    "properties": {
        "current_behavior": {"type": "string"},
        "problematic_code": {"type": "string"},
        "likely_cause": {"type": "string"},
        "proposed_fix": {"type": "string"},
        "proposed_change": {"type": "string"},
        "suggested_code": {"type": "string"},
    },
    "required": [
        "current_behavior",
        "problematic_code",
        "likely_cause",
        "proposed_fix",
        "proposed_change",
        "suggested_code",
    ],
}


class FixBugAnalyzer(BaseAnalyzer):
    def __init__(self, llm_service: LLMService) -> None:
        self.llm_service = llm_service

    async def analyze(self, context: SearchContext) -> AnalysisResult:
        """Analyze fixing a bug using the LLM and the retrieved code context."""
        query_text = context.query
        if context.validation_feedback:
            feedback_str = "\n".join(f"- {err}" for err in context.validation_feedback)
            query_text += f"\n\n[VALIDATION FEEDBACK FROM PREVIOUS ATTEMPT - FIX THESE ISSUES]:\n{feedback_str}"

        user_prompt = FIX_BUG_USER_PROMPT.format(
            context=context.llm_context or "",
            query=query_text,
        )
        try:
            raw = await self.llm_service.provider.complete_json(
                prompt=user_prompt,
                system_prompt=FIX_BUG_SYSTEM_PROMPT,
                schema=_SCHEMA,
            )
            analysis = _coerce(
                raw,
                [
                    "current_behavior",
                    "problematic_code",
                    "likely_cause",
                    "proposed_fix",
                    "proposed_change",
                    "suggested_code",
                ],
            )
        except Exception as exc:
            logger.error("fix_bug_analyzer_failed", exc_info=exc)
            analysis = {"error": str(exc)}

        return AnalysisResult(
            intent="FIX_BUG",
            analysis=analysis,
            validation_result=ValidationResult(is_valid=True),
        )


def _coerce(raw: dict, required_keys: list[str]) -> dict:
    """Return raw if all keys present; add missing keys as empty defaults."""
    for k in required_keys:
        if k not in raw:
            raw[k] = ""
    return raw
