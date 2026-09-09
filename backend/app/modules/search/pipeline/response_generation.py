"""
app/modules/search/pipeline/response_generation.py

Pipeline stage: Response Generation (Step 13 / Final Stage).

Assembles the final compact SearchResponse from information produced
by the previous pipeline stages.

Step 13 is an assembly/presentation stage. It must not perform new
retrieval, analysis, validation, or repository modifications.
"""

from __future__ import annotations

import ast
import json
from typing import Any

from app.modules.search.domain.search_domain import SearchContext
from app.modules.search.schemas.search_schema import SearchResponse


class ResponseGenerationStage:
    """Assemble the final structured search response."""

    _EARLY_EXITS = {
        "EARLY_EXIT_A",
        "EARLY_EXIT_B",
        "EARLY_EXIT_C",
        "EARLY_EXIT_D",
    }

    async def execute(self, context: SearchContext) -> None:
        """Build and store the final compact SearchResponse."""

        intent_str = context.intent.value if context.intent else "unknown"

        repo_info = {
            "id": context.repo_id,
            "owner": context.repo_owner,
            "name": context.repo_name,
        }

        target_info = {
            "file_path": (
                context.primary_chunk.file_path
                if context.primary_chunk
                else None
            ),
            "symbol": self._resolve_target_symbol(context),
        }

        # ---------------------------------------------------------
        # EARLY EXIT
        # ---------------------------------------------------------
        if context.early_exit in self._EARLY_EXITS:
            context.final_response = self._build_early_exit_response(
                context=context,
                intent_str=intent_str,
                repo_info=repo_info,
                target_info=target_info,
            )
            return

        # ---------------------------------------------------------
        # NORMAL RESPONSE
        # ---------------------------------------------------------
        requirement = None
        suggestion: Any = None
        confidence = None

        # ---------------------------------------------------------
        # STEP 11 - TRIAGE RESULT
        # ---------------------------------------------------------
        if context.triage_result:
            requirement = (
                context.triage_result.get("issue_summary")
                or context.triage_result.get("requirement")
            )

            suggestion = (
                context.triage_result.get("ai_suggestion")
                or context.triage_result.get("recommended_change")
                or context.triage_result.get("recommendation")
            )

            confidence = context.triage_result.get("confidence")

        # ---------------------------------------------------------
        # STEP 8 - CODE ANALYSIS RESULT
        # ---------------------------------------------------------
        if context.analysis_result:
            if requirement is None:
                requirement = (
                    context.analysis_result.get("requirement")
                    or context.analysis_result.get("issue_summary")
                )

            if suggestion is None:
                suggestion = (
                    context.analysis_result.get("suggestion")
                    or context.analysis_result.get("recommended_change")
                    or context.analysis_result.get("recommendation")
                )

            if confidence is None:
                confidence = context.analysis_result.get("confidence")

        # ---------------------------------------------------------
        # SearchResponse.suggestion expects a STRING.
        # Convert structured LLM output into a readable string.
        # ---------------------------------------------------------
        suggestion = self._normalize_suggestion(suggestion)

        # ---------------------------------------------------------
        # BUILD FINAL RESPONSE
        # ---------------------------------------------------------
        context.final_response = SearchResponse(
            intent=intent_str,
            repository=repo_info,
            target=target_info,
            requirement=requirement,
            suggestion=suggestion,
            confidence=confidence,
            code_context=context.code_snippets,
            early_exit=None,
        )

    # =============================================================
    # EARLY EXIT RESPONSE
    # =============================================================

    def _build_early_exit_response(
        self,
        context: SearchContext,
        intent_str: str,
        repo_info: dict[str, Any],
        target_info: dict[str, Any],
    ) -> SearchResponse:
        """Build the final response when the pipeline exits early."""

        requirement = None
        suggestion: Any = None
        confidence = None

        if context.triage_result:
            requirement = (
                context.triage_result.get("issue_summary")
                or context.triage_result.get("requirement")
            )

            suggestion = (
                context.triage_result.get("ai_suggestion")
                or context.triage_result.get("recommended_change")
                or context.triage_result.get("recommendation")
            )

            confidence = context.triage_result.get("confidence")

        if context.analysis_result:
            if requirement is None:
                requirement = (
                    context.analysis_result.get("requirement")
                    or context.analysis_result.get("issue_summary")
                )

            if suggestion is None:
                suggestion = (
                    context.analysis_result.get("suggestion")
                    or context.analysis_result.get("recommended_change")
                    or context.analysis_result.get("recommendation")
                )

            if confidence is None:
                confidence = context.analysis_result.get("confidence")

        suggestion = self._normalize_suggestion(suggestion)

        return SearchResponse(
            intent=intent_str,
            repository=repo_info,
            target=target_info,
            requirement=requirement,
            suggestion=suggestion,
            confidence=confidence,
            code_context=context.code_snippets,
            early_exit={
                "code": context.early_exit,
                "message": context.early_exit_message,
            },
        )

    # =============================================================
    # SUGGESTION NORMALIZATION
    # =============================================================

    @staticmethod
    def _normalize_suggestion(suggestion: Any) -> str | None:
        """
        Convert any suggestion value into the string expected by
        SearchResponse.suggestion.

        If the LLM returns a structured dictionary, prefer its
        description. If no description exists, serialize the
        structure as JSON.
        """

        if suggestion is None:
            return None

        # ---------------------------------------------------------
        # Structured dictionary returned directly by the LLM.
        # ---------------------------------------------------------
        if isinstance(suggestion, dict):
            description = suggestion.get("description")

            if description is not None:
                if isinstance(description, str):
                    return description.strip() or None

                return str(description)

            return json.dumps(
                suggestion,
                ensure_ascii=False,
            )

        # ---------------------------------------------------------
        # List returned directly by the LLM.
        # ---------------------------------------------------------
        if isinstance(suggestion, list):
            return json.dumps(
                suggestion,
                ensure_ascii=False,
            )

        # ---------------------------------------------------------
        # Already a string.
        # ---------------------------------------------------------
        if isinstance(suggestion, str):
            value = suggestion.strip()

            if not value:
                return None

            # Try JSON first.
            try:
                parsed = json.loads(value)

                if isinstance(parsed, dict):
                    description = parsed.get("description")

                    if description is not None:
                        if isinstance(description, str):
                            return description.strip() or None

                        return str(description)

                    return json.dumps(
                        parsed,
                        ensure_ascii=False,
                    )

                if isinstance(parsed, list):
                    return json.dumps(
                        parsed,
                        ensure_ascii=False,
                    )

            except (json.JSONDecodeError, TypeError, ValueError):
                pass

            # Try Python repr.
            try:
                parsed = ast.literal_eval(value)

                if isinstance(parsed, dict):
                    description = parsed.get("description")

                    if description is not None:
                        if isinstance(description, str):
                            return description.strip() or None

                        return str(description)

                    return json.dumps(
                        parsed,
                        ensure_ascii=False,
                    )

                if isinstance(parsed, list):
                    return json.dumps(
                        parsed,
                        ensure_ascii=False,
                    )

            except (ValueError, SyntaxError, TypeError):
                pass

            return value

        # ---------------------------------------------------------
        # Any other type.
        # ---------------------------------------------------------
        return str(suggestion)

    # =============================================================
    # TARGET SYMBOL
    # =============================================================

    @staticmethod
    def _resolve_target_symbol(context: SearchContext) -> str | None:
        """
        Resolve the most useful target symbol.

        Prefer an already meaningful target symbol.

        If the target symbol is a filename or is otherwise unavailable,
        use the primary chunk metadata to resolve the class/function.
        """

        target_symbol = context.target_symbol
        primary_chunk = context.primary_chunk

        metadata = (
            primary_chunk.metadata
            if primary_chunk and primary_chunk.metadata
            else {}
        )

        class_name = str(
            metadata.get("class_name") or ""
        ).strip()

        function_name = str(
            metadata.get("function_name") or ""
        ).strip()

        file_path = (
            primary_chunk.file_path
            if primary_chunk
            else None
        )

        # ---------------------------------------------------------
        # If target_symbol is meaningful and is not just the file path,
        # keep it.
        # ---------------------------------------------------------
        if target_symbol:
            normalized = target_symbol.strip()

            if normalized and normalized != file_path:
                if not normalized.lower().endswith(
                    (
                        ".ts",
                        ".tsx",
                        ".js",
                        ".jsx",
                        ".py",
                        ".java",
                        ".go",
                        ".rs",
                        ".cpp",
                        ".c",
                        ".cs",
                    )
                ):
                    return normalized

        # ---------------------------------------------------------
        # Prefer class name from chunk metadata.
        # ---------------------------------------------------------
        if class_name:
            return class_name

        # ---------------------------------------------------------
        # Fall back to function/method name.
        # ---------------------------------------------------------
        if function_name:
            return function_name

        # ---------------------------------------------------------
        # Last fallback.
        # ---------------------------------------------------------
        return target_symbol