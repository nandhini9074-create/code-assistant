"""
app/modules/code_analysis/analyzers/add_feature_analyzer.py
Analyzer for ADD_FEATURE intent.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.modules.code_analysis.analyzers.base_analyzer import BaseAnalyzer
from app.modules.code_analysis.domain.analysis_domain import (
    AnalysisResult,
    ValidationResult,
)
from app.modules.code_analysis.prompts.add_feature_prompt import (
    ADD_FEATURE_SYSTEM_PROMPT,
    ADD_FEATURE_USER_PROMPT,
)
from app.modules.llm.service.llm_service import LLMService
from app.modules.search.domain.search_domain import SearchContext

logger = get_logger(__name__)


_SCHEMA = {
    "type": "object",
    "properties": {
        "existing_implementation": {
            "type": "string",
        },
        "proposed_change": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                },
                "implementation_steps": {
                    "type": "array",
                    "items": {
                        "type": "string",
                    },
                },
            },
            "required": [
                "description",
                "implementation_steps",
            ],
            "additionalProperties": False,
        },
        "required_changes": {
            "type": "array",
            "items": {
                "type": "string",
            },
        },
        "affected_files": {
            "type": "array",
            "items": {
                "type": "string",
            },
        },
        "risks": {
            "type": "string",
        },
    },
    "required": [
        "existing_implementation",
        "proposed_change",
        "required_changes",
        "affected_files",
        "risks",
    ],
    "additionalProperties": False,
}


class AddFeatureAnalyzer(BaseAnalyzer):
    def __init__(self, llm_service: LLMService) -> None:
        self.llm_service = llm_service

    async def analyze(self, context: SearchContext) -> AnalysisResult:
        """Analyse adding a feature using the LLM and retrieved code context."""

        query_text = context.query

        if context.validation_feedback:
            feedback_str = "\n".join(
                f"- {err}" for err in context.validation_feedback
            )
            query_text += (
                "\n\n"
                "[VALIDATION FEEDBACK FROM PREVIOUS ATTEMPT - "
                "FIX THESE ISSUES]:\n"
                f"{feedback_str}"
            )

        user_prompt = ADD_FEATURE_USER_PROMPT.format(
            context=context.llm_context or "",
            query=query_text,
        )

        try:
            raw = await self.llm_service.provider.complete_json(
                prompt=user_prompt,
                system_prompt=ADD_FEATURE_SYSTEM_PROMPT,
                schema=_SCHEMA,
            )

            analysis = _coerce(raw)

        except Exception as exc:
            logger.error(
                "add_feature_analyzer_failed",
                exc_info=exc,
            )

            analysis = {
                "error": str(exc),
                "existing_implementation": "",
                "proposed_change": {
                    "description": "",
                    "implementation_steps": [],
                },
                "required_changes": [],
                "affected_files": [],
                "risks": "",
            }

        return AnalysisResult(
            intent="ADD_FEATURE",
            analysis=analysis,
            validation_result=ValidationResult(is_valid=True),
        )


def _coerce(raw: dict) -> dict:
    """Normalize the LLM response to the expected analysis structure."""

    if not isinstance(raw, dict):
        raw = {}

    raw.setdefault("existing_implementation", "")

    proposed_change = raw.get("proposed_change")

    if not isinstance(proposed_change, dict):
        proposed_change = {
            "description": (
                proposed_change
                if isinstance(proposed_change, str)
                else ""
            ),
            "implementation_steps": [],
        }

    proposed_change.setdefault("description", "")
    proposed_change.setdefault("implementation_steps", [])

    if not isinstance(proposed_change["implementation_steps"], list):
        proposed_change["implementation_steps"] = []

    raw["proposed_change"] = proposed_change

    if not isinstance(raw.get("required_changes"), list):
        raw["required_changes"] = []

    if not isinstance(raw.get("affected_files"), list):
        raw["affected_files"] = []

    raw.setdefault("risks", "")

    return raw