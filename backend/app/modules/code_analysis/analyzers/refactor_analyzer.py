"""
app/modules/code_analysis/analyzers/refactor_analyzer.py
Analyzer for REFACTOR intent.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.modules.code_analysis.analyzers.base_analyzer import BaseAnalyzer
from app.modules.code_analysis.domain.analysis_domain import AnalysisResult, ValidationResult
from app.modules.code_analysis.prompts.refactor_prompt import (
    REFACTOR_SYSTEM_PROMPT,
    REFACTOR_USER_PROMPT,
)
from app.modules.llm.service.llm_service import LLMService
from app.modules.search.domain.search_domain import SearchContext

logger = get_logger(__name__)

_SCHEMA = {
    "type": "object",
    "properties": {
        "code_smell": {"type": "string"},
        "duplication": {"type": "string"},
        "safe_refactoring_plan": {"type": "string"},
    },
    "required": ["code_smell", "duplication", "safe_refactoring_plan"],
}


class RefactorAnalyzer(BaseAnalyzer):
    def __init__(self, llm_service: LLMService) -> None:
        self.llm_service = llm_service

    async def analyze(self, context: SearchContext) -> AnalysisResult:
        """Analyze code for refactoring using the LLM and the retrieved code context."""
        query_text = context.query
        if context.validation_feedback:
            feedback_str = "\n".join(f"- {err}" for err in context.validation_feedback)
            query_text += f"\n\n[VALIDATION FEEDBACK FROM PREVIOUS ATTEMPT - FIX THESE ISSUES]:\n{feedback_str}"

        user_prompt = REFACTOR_USER_PROMPT.format(
            context=context.llm_context or "",
            query=query_text,
        )
        try:
            raw = await self.llm_service.provider.complete_json(
                prompt=user_prompt,
                system_prompt=REFACTOR_SYSTEM_PROMPT,
                schema=_SCHEMA,
            )
            analysis = _coerce(raw, ["code_smell", "duplication", "safe_refactoring_plan"])
        except Exception as exc:
            logger.error("refactor_analyzer_failed", exc_info=exc)
            analysis = {"error": str(exc)}

        return AnalysisResult(
            intent="REFACTOR",
            analysis=analysis,
            validation_result=ValidationResult(is_valid=True),
        )


def _coerce(raw: dict, required_keys: list[str]) -> dict:
    """Return raw if all keys present; add missing keys as empty defaults."""
    for k in required_keys:
        if k not in raw:
            raw[k] = ""
    return raw
