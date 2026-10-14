
"""
app/modules/code_analysis/analyzers/fix_bug_analyzer.py

Analyzer for FIX_BUG intent.

Responsibilities:
- Analyze retrieved repository evidence.
- Reject unsupported or unverifiable fixes.
- Validate proposed patch targets against retrieved chunks.
- Preserve UNAVAILABLE behavior when analysis or evidence is insufficient.

Deep Search orchestration belongs to the search pipeline, not this analyzer.
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

MAX_OUTPUT_TOKENS = 2048
MAX_CONTEXT_CHARS = 12000


_SCHEMA = {
    "type": "object",
    "properties": {
        "current_behavior": {"type": "string"},
        "analysis_status": {
            "type": "string",
            "enum": ["OK", "UNAVAILABLE"],
        },
        "evidence_summary": {"type": "string"},
        "problematic_code": {"type": "string"},
        "likely_cause": {"type": "string"},
        "proposed_fix": {"type": "string"},
        "proposed_change": {"type": "string"},
        "code_change": {
            "anyOf": [
                {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                        "symbol": {"type": ["string", "null"]},
                        "start_line": {"type": ["integer", "null"]},
                        "end_line": {"type": ["integer", "null"]},
                        "old_code": {"type": "string"},
                        "new_code": {"type": "string"},
                    },
                    "required": [
                        "file_path",
                        "symbol",
                        "start_line",
                        "end_line",
                        "old_code",
                        "new_code",
                    ],
                    "additionalProperties": False,
                },
                {"type": "null"},
            ]
        },
        "suggested_code": {"type": "string"},
    },
    "required": [
        "current_behavior",
        "analysis_status",
        "evidence_summary",
        "problematic_code",
        "likely_cause",
        "proposed_fix",
        "proposed_change",
        "code_change",
        "suggested_code",
    ],
}


class FixBugAnalyzer(BaseAnalyzer):
    """Analyze bug reports using retrieved repository evidence."""

    def __init__(self, llm_service: LLMService) -> None:
        self.llm_service = llm_service

    async def analyze(self, context: SearchContext) -> AnalysisResult:
        """
        Analyze a FIX_BUG request.

        The search pipeline chooses normal retrieval or Deep Search.
        This analyzer consumes the evidence supplied by that pipeline
        and does not initiate another retrieval workflow.
        """

        query_text = context.query

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

        repository_context = _limit_context(
            context.llm_context or ""
        )

        # Include the diagnosis produced by Deep Search when available.
        deep_search_result = getattr(
            context,
            "deep_search_result",
            None,
        )

        if isinstance(deep_search_result, dict):
            diagnosis = deep_search_result.get("diagnosis")

            if isinstance(diagnosis, str) and diagnosis.strip():
                ds_str = (
                    "[DEEP SEARCH INVESTIGATION DIAGNOSIS]:\n"
                    f"{diagnosis.strip()}"
                )

                if ds_str not in repository_context:
                    repository_context = (
                        f"{ds_str}\n\n{repository_context}"
                    )

        user_prompt = FIX_BUG_USER_PROMPT.format(
            context=repository_context,
            query=query_text,
        )

        logger.info(
            "fix_bug_prompt_size",
            prompt_chars=len(user_prompt),
            context_chars=len(repository_context),
            query_chars=len(query_text),
            validation_feedback_count=len(
                context.validation_feedback
            ),
            deep_search_used=isinstance(
                deep_search_result,
                dict,
            ),
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
                    "analysis_status",
                    "evidence_summary",
                    "current_behavior",
                    "problematic_code",
                    "likely_cause",
                    "proposed_fix",
                    "proposed_change",
                    "code_change",
                    "suggested_code",
                ],
            )

            analysis["analysis_status"] = (
                str(
                    analysis.get("analysis_status")
                    or "UNAVAILABLE"
                )
                .strip()
                .upper()
            )

            # Validate the LLM result against actual repository evidence.
            if (
                analysis["analysis_status"] != "OK"
                or not _has_concrete_evidence(analysis, context)
            ):
                analysis["analysis_status"] = "UNAVAILABLE"
                analysis["code_change"] = None
                analysis["suggested_code"] = ""

                analysis["evidence_summary"] = (
                    str(
                        analysis.get("evidence_summary") or ""
                    ).strip()
                    or (
                        "The retrieved repository evidence does not "
                        "establish a verifiable cause and patch target."
                    )
                )

            # Ensure unavailable analyses cannot return a proposed patch.
            if analysis["analysis_status"] != "OK":
                analysis["analysis_status"] = "UNAVAILABLE"
                analysis["code_change"] = None
                analysis["suggested_code"] = ""

            logger.info(
                "fix_bug_analysis_completed",
                analysis_status=analysis["analysis_status"],
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

            # Preserve centralized failure handling.
            raise RuntimeError(
                f"FIX_BUG analysis failed: {exc}"
            ) from exc


def _limit_context(context_text: str) -> str:
    """Bound the repository context sent to the analysis LLM."""

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
        "Only the provided repository evidence may be used."
    )


def _coerce(raw: dict, required_keys: list[str]) -> dict:
    """Fill missing response keys without inventing analysis results."""

    result = dict(raw)

    for key in required_keys:
        if key not in result:
            result[key] = None if key == "code_change" else ""

    if not isinstance(result.get("code_change"), dict):
        result["code_change"] = None

    return result


def _normalize_path(path: object) -> str:
    """
    Normalize repository paths for comparison.

    Handles Windows separators, leading './', repeated separators,
    and case differences without assuming the current working
    directory is the repository root.
    """

    value = str(path or "").strip().replace("\\", "/")

    while value.startswith("./"):
        value = value[2:]

    while "//" in value:
        value = value.replace("//", "/")

    return value.rstrip("/").casefold()


def _paths_match(first: str, second: str) -> bool:
    """
    Match repository-relative paths against paths containing a
    repository-root prefix.

    Matching requires a complete path-component boundary, avoiding
    accidental matches such as 'src/app.py' against 'old_src/app.py'.
    """

    first = _normalize_path(first)
    second = _normalize_path(second)

    if not first or not second:
        return False

    if first == second:
        return True

    return (
        first.endswith("/" + second)
        or second.endswith("/" + first)
    )


def _has_concrete_evidence(
    analysis: dict,
    context: SearchContext,
) -> bool:
    """
    Verify the analysis against retrieved repository evidence.

    When a patch is proposed, its target file must exist in the
    retrieved evidence, and old_code must match the retrieved content.
    """

    evidence_summary = str(
        analysis.get("evidence_summary") or ""
    ).strip()

    if not evidence_summary:
        return False

    retrieved_chunks = list(context.retrieved_chunks or [])

    if not retrieved_chunks:
        return False

    code_change = analysis.get("code_change")

    if code_change is None:
        # An explanation without a patch is permitted only when
        # repository evidence exists and the LLM reports status OK.
        return True

    if not isinstance(code_change, dict):
        return False

    target_path = _normalize_path(
        code_change.get("file_path")
    )

    old_code = code_change.get("old_code")
    new_code = code_change.get("new_code")

    if not target_path:
        return False

    if not isinstance(old_code, str) or not old_code.strip():
        return False

    if not isinstance(new_code, str) or not new_code.strip():
        return False

    matching_chunks = []

    for chunk in retrieved_chunks:
        chunk_path = _normalize_path(
            getattr(chunk, "file_path", "")
        )

        if not chunk_path:
            continue

        if _paths_match(chunk_path, target_path):
            matching_chunks.append(chunk)

    if not matching_chunks:
        logger.warning(
            "fix_bug_patch_target_not_in_retrieved_evidence",
            target_path=target_path,
        )
        return False

    # Strict validation: old_code must occur in a retrieved chunk
    # belonging to the proposed patch target.
    for chunk in matching_chunks:
        chunk_content = getattr(chunk, "content", "")

        if (
            isinstance(chunk_content, str)
            and old_code in chunk_content
        ):
            return True

    logger.warning(
        "fix_bug_patch_old_code_not_in_retrieved_evidence",
        target_path=target_path,
    )

    return False
