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
        # STEP 12 - TRIAGE RESULT
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
        # STEP 9 - CODE ANALYSIS RESULT
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
        # IMPORTANT:
        # Triage may convert a dictionary into a Python string such as:
        #
        # "{'description': '...', 'implementation_steps': [...]}"
        #
        # Convert it back into a real JSON-compatible object.
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
            early_exit=context.early_exit,
        )

    # =============================================================
    # SUGGESTION NORMALIZATION
    # =============================================================

    @staticmethod
    def _normalize_suggestion(suggestion: Any) -> Any:
        """
        Convert stringified dictionaries/lists into real Python
        dictionaries/lists before constructing SearchResponse.

        Handles:
            1. Already structured dict/list
            2. Valid JSON strings
            3. Python repr strings containing single quotes
            4. Empty strings
            5. Invalid strings

        Example input:

            "{'description': 'Add EmailService',
              'implementation_steps': ['Step 1', 'Step 2']}"

        Becomes:

            {
                "description": "Add EmailService",
                "implementation_steps": [
                    "Step 1",
                    "Step 2"
                ]
            }
        """

        # Already structured.
        if isinstance(suggestion, (dict, list)):
            return suggestion

        # Nothing to normalize.
        if suggestion is None:
            return None

        if not isinstance(suggestion, str):
            return suggestion

        value = suggestion.strip()

        if not value:
            return None

        # ---------------------------------------------------------
        # First try strict JSON.
        # ---------------------------------------------------------
        try:
            parsed = json.loads(value)

            if isinstance(parsed, (dict, list)):
                return parsed

        except (json.JSONDecodeError, TypeError, ValueError):
            pass

        # ---------------------------------------------------------
        # Then handle Python dictionary representation.
        #
        # Example:
        # "{'description': '...', 'implementation_steps': [...]}"
        # ---------------------------------------------------------
        try:
            parsed = ast.literal_eval(value)

            if isinstance(parsed, (dict, list)):
                return parsed

        except (ValueError, SyntaxError, TypeError):
            pass

        # ---------------------------------------------------------
        # If it cannot safely be parsed, preserve the original
        # string rather than crashing the response pipeline.
        # ---------------------------------------------------------
        return suggestion

    # =============================================================
    # TARGET SYMBOL
    # =============================================================

    @staticmethod
    def _resolve_target_symbol(context: SearchContext) -> str | None:
        """
        Resolve the most useful target symbol.

        Prefer the symbol selected by the analysis pipeline.

        If target_symbol accidentally contains only a filename
        such as:

            payout-transaction.service.ts

        use the primary chunk's class/function information instead.
        """

        target_symbol = context.target_symbol

        primary_chunk = context.primary_chunk

        # ---------------------------------------------------------
        # If target_symbol is already a meaningful symbol, keep it.
        # ---------------------------------------------------------
        if target_symbol:
            normalized = target_symbol.strip()

            if (
                normalized
                and primary_chunk
                and normalized != primary_chunk.file_path
            ):
                return normalized

            if normalized and not normalized.lower().endswith(
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
        # Prefer class name.
        # ---------------------------------------------------------
        if primary_chunk:
            class_name = getattr(primary_chunk, "class_name", None)

            if class_name:
                class_name = str(class_name).strip()

                if class_name:
                    return class_name

        # ---------------------------------------------------------
        # Fall back to function/method name.
        # ---------------------------------------------------------
        if primary_chunk:
            function_name = getattr(primary_chunk, "function_name", None)

            if function_name:
                function_name = str(function_name).strip()

                if function_name:
                    return function_name

        # ---------------------------------------------------------
        # Last fallback.
        # ---------------------------------------------------------
        return target_symbol