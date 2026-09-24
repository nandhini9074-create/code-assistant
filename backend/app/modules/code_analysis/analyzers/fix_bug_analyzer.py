
"""
app/modules/code_analysis/analyzers/fix_bug_analyzer.py

Analyzer for FIX_BUG intent.
"""

from __future__ import annotations

from app.core.logging import get_logger

from app.modules.code_analysis.analyzers.base_analyzer import BaseAnalyzer
from app.modules.code_analysis.domain.analysis_domain import (
    AnalysisResult,
    ValidationResult,
)
from app.modules.code_analysis.prompts.fix_bug_prompt import (
    FIX_BUG_SYSTEM_PROMPT,
    FIX_BUG_USER_PROMPT,
)
from app.modules.llm.service.llm_service import LLMService
from app.modules.search.domain.search_domain import SearchContext


logger = get_logger(__name__)


# Keep the output bounded so the model does not spend the entire
# completion budget generating a large code response.
MAX_OUTPUT_TOKENS = 2048

# Maximum repository-context characters sent to the FIX_BUG analyzer.
#
# This is a safety limit for the analysis prompt. The retrieved context
# should already have been selected by the search pipeline.
MAX_CONTEXT_CHARS = 12000


_SCHEMA = {
    "type": "object",
    "properties": {
        "current_behavior": {
            "type": "string",
        },
        "problematic_code": {
            "type": "string",
        },
        "likely_cause": {
            "type": "string",
        },
        "proposed_fix": {
            "type": "string",
        },
        "proposed_change": {
            "type": "string",
        },
        "code_change": {
            "anyOf": [
                {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                        "old_code": {"type": "string"},
                        "new_code": {"type": "string"},
                    },
                    "required": ["file_path", "old_code", "new_code"],
                    "additionalProperties": False,
                },
                {"type": "null"},
            ]
        },
        "suggested_code": {
            "type": "string",
        },
    },
    "required": [
        "current_behavior",
        "problematic_code",
        "likely_cause",
        "proposed_fix",
        "proposed_change",
        "code_change",
        "suggested_code",
    ],
}


class FixBugAnalyzer(BaseAnalyzer):

    def __init__(self, llm_service: LLMService) -> None:
        self.llm_service = llm_service

    async def analyze(self, context: SearchContext) -> AnalysisResult:
        """
        Analyze a FIX_BUG request using the retrieved repository context.

        The analyzer:
        1. Uses the original bug query.
        2. Adds validation feedback when retrying.
        3. Limits the repository context sent to the LLM.
        4. Requests a compact structured JSON response.
        5. Propagates LLM failures to CodeAnalysisStage so the
           centralized UNAVAILABLE fallback can be applied.
        """

        query_text = context.query

        # Add validation feedback only when a previous validation attempt
        # has provided concrete feedback.
        if context.validation_feedback:
            feedback_str = "\n".join(
                f"- {error}"
                for error in context.validation_feedback
            )

            query_text += (
                "\n\n"
                "[VALIDATION FEEDBACK FROM PREVIOUS ATTEMPT - "
                "FIX THESE ISSUES]:\n"
                f"{feedback_str}"
            )

        # Limit the context before constructing the final LLM prompt.
        repository_context = _limit_context(
            context.llm_context or ""
        )

        user_prompt = FIX_BUG_USER_PROMPT.format(
            context=repository_context,
            query=query_text,
        )

        # Useful diagnostic information for token/prompt debugging.
        logger.info(
            "fix_bug_prompt_size",
            prompt_chars=len(user_prompt),
            context_chars=len(repository_context),
            query_chars=len(query_text),
            validation_feedback_count=len(context.validation_feedback),
        )

        try:
            raw = await self.llm_service.provider.complete_json(
                prompt=user_prompt,
                system_prompt=FIX_BUG_SYSTEM_PROMPT,
                schema=_SCHEMA,
                max_tokens=MAX_OUTPUT_TOKENS,
            )

            if not isinstance(raw, dict):
                raise ValueError(
                    "FIX_BUG LLM response was not a JSON object."
                )

            analysis = _coerce(
                raw,
                [
                    "current_behavior",
                    "problematic_code",
                    "likely_cause",
                    "proposed_fix",
                    "proposed_change",
                    "code_change",
                    "suggested_code",
                ],
            )

            logger.info(
                "fix_bug_analysis_completed",
                suggested_code_chars=len(
                    analysis.get("suggested_code", "")
                ),
                problematic_code_chars=len(
                    analysis.get("problematic_code", "")
                ),
            )

            return AnalysisResult(
                intent="FIX_BUG",
                analysis=analysis,
                validation_result=ValidationResult(
                    is_valid=True,
                ),
            )

        except Exception as exc:
            logger.error(
                "fix_bug_analyzer_failed",
                error=str(exc),
                exc_info=True,
            )

            # Do not return an empty AnalysisResult here.
            #
            # Returning AnalysisResult would make the failed LLM call
            # look like a completed analysis to CodeAnalysisService.
            #
            # Propagate the failure so CodeAnalysisStage can create the
            # standardized UNAVAILABLE fallback.
            raise RuntimeError(
                f"FIX_BUG analysis failed: {exc}"
            ) from exc


def _limit_context(context_text: str) -> str:
    """
    Limit repository context sent to the FIX_BUG LLM.

    The search pipeline may retrieve several chunks. Sending all of them
    can unnecessarily increase prompt size and make structured JSON
    generation harder.

    The beginning of the context is preserved because ContextBuilder
    normally places the most relevant/primary code there.
    """

    if not context_text:
        return ""

    if len(context_text) <= MAX_CONTEXT_CHARS:
        return context_text

    logger.warning(
        "fix_bug_context_truncated",
        original_chars=len(context_text),
        max_chars=MAX_CONTEXT_CHARS,
    )

    return (
        context_text[:MAX_CONTEXT_CHARS]
        + "\n\n"
        "[CONTEXT TRUNCATED FOR FIX_BUG ANALYSIS]\n"
        "Only the provided context above may be used."
    )


def _coerce(raw: dict, required_keys: list[str]) -> dict:
    """
    Return raw with missing required keys added as empty strings.
    """

    for key in required_keys:
        if key not in raw:
            raw[key] = "" if key != "code_change" else None

    if raw.get("code_change") is None:
        raw["code_change"] = None

    return raw