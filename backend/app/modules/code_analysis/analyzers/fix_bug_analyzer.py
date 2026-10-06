
"""
app/modules/code_analysis/analyzers/fix_bug_analyzer.py

Analyzer for FIX_BUG intent.
"""

from __future__ import annotations

import re

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
        "analysis_status": {
            "type": "string",
            "enum": ["OK", "UNAVAILABLE"],
        },
        "evidence_summary": {
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
        "suggested_code": {
            "type": "string",
        },
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

        # ---------------------------------------------------------
        # Model-Schema Contract Analysis
        # ---------------------------------------------------------
        from app.modules.search.pipeline.model_schema_contract_analysis import (
            ContractIssueType,
            ModelSchemaContractAnalyzer,
            format_contract_evidence_for_llm,
        )

        contract_analyzer = ModelSchemaContractAnalyzer()
        contract_result = contract_analyzer.analyze(context)
        context.contract_analysis = contract_result.to_dict()

        contract_fact_str = ""
        if contract_result.is_applicable:
            contract_fact_str = format_contract_evidence_for_llm(contract_result)

        # Limit the context before constructing the final LLM prompt.
        repository_context = _limit_context(
            context.llm_context or ""
        )

        if contract_fact_str and contract_fact_str not in repository_context:
            repository_context = f"{contract_fact_str}\n\n{repository_context}"

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
            contract_applicable=contract_result.is_applicable,
            contract_issue_type=contract_result.issue_type.value,
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

            analysis["analysis_status"] = str(
                analysis.get("analysis_status") or "UNAVAILABLE"
            ).strip().upper()

            # If contract analysis found insufficient evidence or ambiguity, enforce UNAVAILABLE
            if (
                contract_result.is_applicable
                and contract_result.issue_type in (
                    ContractIssueType.AMBIGUOUS,
                    ContractIssueType.INSUFFICIENT_EVIDENCE,
                )
                and not contract_result.verified_facts.get("field_present")
            ):
                analysis["analysis_status"] = "UNAVAILABLE"
                analysis["code_change"] = None
                analysis["suggested_code"] = ""
                analysis["evidence_summary"] = contract_result.evidence_summary

            elif (
                analysis["analysis_status"] != "OK"
                or not _has_concrete_evidence(analysis, context)
            ):
                analysis["analysis_status"] = "UNAVAILABLE"
                analysis["code_change"] = None
                analysis["suggested_code"] = ""
                analysis["evidence_summary"] = str(
                    analysis.get("evidence_summary")
                    or "The retrieved code does not establish a specific cause."
                )

            # Rule 8: Never automatically suggest adding a database/model field when
            # the issue is a mapping mismatch or wrong field reference
            if (
                contract_result.is_applicable
                and contract_result.field_confirmed_absent
                and contract_result.issue_type in (
                    ContractIssueType.FIELD_MAPPING_MISMATCH,
                    ContractIssueType.WRONG_FIELD_REFERENCE,
                )
                and isinstance(analysis.get("code_change"), dict)
            ):
                model_fp = (
                    contract_result.model_definition.file_path.replace("\\", "/").lower()
                    if contract_result.model_definition
                    else ""
                )
                cc_fp = str(analysis["code_change"].get("file_path") or "").replace("\\", "/").lower()
                # If code change attempts to add fields to the database model file instead of the caller/schema
                if model_fp and (cc_fp.endswith(model_fp) or model_fp.endswith(cc_fp)):
                    logger.warning(
                        "fix_bug_prevented_unsafe_model_modification",
                        target_model=model_fp,
                        issue_type=contract_result.issue_type.value,
                    )
                    analysis["code_change"] = None
                    analysis["suggested_code"] = ""
                    analysis["proposed_fix"] = (
                        f"Update the {contract_result.issue_type.value.lower().replace('_', ' ')} "
                        f"to use verified field '{contract_result.equivalent_field}' "
                        f"instead of modifying the database model."
                    )

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


def _has_concrete_evidence(
    analysis: dict,
    context: SearchContext,
) -> bool:
    """Require report-linked evidence and exact target code from retrieved chunks."""
    evidence_summary = str(analysis.get("evidence_summary") or "").lower()
    if not evidence_summary.strip():
        return False
    query_terms = {
        term.lower()
        for term in re.findall(
            r"[A-Za-z][A-Za-z0-9]*",
            context.query,
        )
    }
    generic_terms = {
        "fix", "bug", "the", "a", "an", "in", "on", "at", "to", "for",
        "with", "error", "issue", "problem", "please", "wrong", "broken",
    }
    report_terms = query_terms - generic_terms
    if report_terms and not any(
        re.search(rf"(?<!\w){re.escape(term)}(?!\w)", evidence_summary)
        for term in report_terms
    ):
        return False

    code_change = analysis.get("code_change")
    if code_change is not None and not isinstance(code_change, dict):
        return False

    target_path = (
        str(code_change.get("file_path") or "").replace("\\", "/").lower()
        if isinstance(code_change, dict)
        else ""
    )
    if isinstance(code_change, dict) and not target_path:
        return False

    evidence_chunks = []
    for chunk in context.retrieved_chunks:
        chunk_path = (chunk.file_path or "").replace("\\", "/").lower()
        if target_path and not (
            chunk_path.endswith(target_path)
            or target_path.endswith(chunk_path)
        ):
            continue

        basename = chunk_path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        symbols = [
            str(chunk.metadata.get(key) or "").strip().lower()
            for key in ("function_name", "class_name", "symbol")
        ]
        symbols = [symbol for symbol in symbols if symbol]
        file_named = chunk_path in evidence_summary or basename in evidence_summary
        symbol_named = not symbols or any(
            symbol in evidence_summary for symbol in symbols
        )
        if file_named and symbol_named:
            evidence_chunks.append(chunk)

    if not evidence_chunks:
        return False
    if code_change is None:
        return True

    old_code = code_change.get("old_code")
    return (
        isinstance(old_code, str)
        and bool(old_code.strip())
        and any(old_code in chunk.content for chunk in evidence_chunks)
    )