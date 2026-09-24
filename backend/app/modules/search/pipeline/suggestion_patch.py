
"""
Suggestion-only patch generation stage.

This stage does NOT modify the repository.
It generates a real unified diff in memory for the caller to review.
"""

from __future__ import annotations

import difflib
from typing import Any

from app.core.enums import IntentType
from app.core.logging import get_logger
from app.modules.search.domain.search_domain import SearchContext

logger = get_logger(__name__)


class SuggestionPatchStage:
    """Generate a real patch suggestion without writing files."""

    async def execute(self, context: SearchContext) -> None:
        if context.early_exit:
            logger.info(
                "suggestion_patch_skipped",
                reason=context.early_exit,
                repo_id=context.repo_id,
            )
            return

        if context.intent in (None, IntentType.RETRIEVE):
            context.suggested_patch = None
            context.patch_validation = None
            return

        if not context.analysis_result:
            context.suggested_patch = None
            context.patch_validation = None
            return

        analysis = context.analysis_result or {}
        action = context.action_analysis or {}

        patch_text, validation = self._build_patch(
            context=context,
            analysis=analysis,
            action=action,
        )

        context.suggested_patch = patch_text
        context.patch_validation = validation

        logger.info(
            "suggestion_patch_generated",
            repo_id=context.repo_id,
            intent=context.intent.value if context.intent else None,
            patch_length=len(patch_text or ""),
            validation_status=validation.get("status"),
        )

    def _build_patch(
        self,
        context: SearchContext,
        analysis: dict[str, Any],
        action: dict[str, Any],
    ) -> tuple[str | None, dict[str, Any]]:
        """Build a real unified diff from original and suggested code."""

        file_path = self._get_file_path(context, action)

        exact_change = self._extract_exact_code_change(action, analysis)
        if isinstance(exact_change, dict):
            expected_path = exact_change.get("file_path")
            if isinstance(expected_path, str) and expected_path.strip() and file_path and expected_path.strip() != file_path:
                return None, {
                    "status": "failed",
                    "message": "The exact code_change file_path does not match the retrieved source file.",
                    "warnings": [
                        "Patch generation was aborted because the target file could not be confirmed."
                    ],
                    "test_suggestions": self._build_test_suggestions(context),
                }

        original_code = self._get_original_code(context, analysis, action)
        suggested_code = self._get_suggested_code(analysis, action)

        if not file_path:
            return None, {
                "status": "failed",
                "message": "Unable to determine the target file.",
                "warnings": ["No target file path was available."],
                "test_suggestions": self._build_test_suggestions(context),
            }

        if not original_code:
            return None, {
                "status": "failed",
                "message": (
                    "Unable to generate a patch because the original "
                    "source code was not available in the retrieved context."
                ),
                "warnings": [
                    "Original code is required to generate a real unified diff."
                ],
                "test_suggestions": self._build_test_suggestions(context),
            }

        if not suggested_code:
            return None, {
                "status": "failed",
                "message": (
                    "Unable to generate a patch because the LLM did not "
                    "provide suggested code."
                ),
                "warnings": [
                    "Suggested code is required to generate a real unified diff."
                ],
                "test_suggestions": self._build_test_suggestions(context),
            }

        original_code = self._normalize_code(original_code)
        suggested_code = self._normalize_code(suggested_code)

        if original_code == suggested_code:
            return None, {
                "status": "failed",
                "message": "No code change was detected.",
                "warnings": [
                    "Original code and suggested code are identical."
                ],
                "test_suggestions": self._build_test_suggestions(context),
            }

        patch_lines = list(
            difflib.unified_diff(
                original_code.splitlines(),
                suggested_code.splitlines(),
                fromfile=f"a/{file_path}",
                tofile=f"b/{file_path}",
                lineterm="",
                n=3,
            )
        )

        if not patch_lines:
            return None, {
                "status": "failed",
                "message": "Unable to generate a non-empty diff.",
                "warnings": ["No differences were detected."],
                "test_suggestions": self._build_test_suggestions(context),
            }

        patch_text = "\n".join(patch_lines)

        return patch_text, {
            "status": "passed",
            "message": (
                "A real unified diff was generated in memory. "
                "Repository files were not modified."
            ),
            "warnings": [],
            "checks": [
                "Target file identified.",
                "Original source code was available.",
                "Suggested source code was available.",
                "Original and suggested code differ.",
                "Unified diff generated successfully.",
                "Repository files were not modified.",
            ],
            "test_suggestions": self._build_test_suggestions(context),
        }

    def _get_file_path(
        self,
        context: SearchContext,
        action: dict[str, Any],
    ) -> str | None:
        """Resolve the actual target file."""

        exact_change = self._extract_exact_code_change(action)
        if exact_change and isinstance(exact_change.get("file_path"), str):
            return exact_change["file_path"].strip() or None

        target = (
            action.get("affected_target")
            if isinstance(action, dict)
            else None
        )

        if isinstance(target, dict):
            file_path = target.get("file_path")
            if file_path:
                return str(file_path)

        if context.primary_chunk:
            file_path = getattr(
                context.primary_chunk,
                "file_path",
                None,
            )
            if file_path:
                return str(file_path)

        return None

    def _get_original_code(
        self,
        context: SearchContext,
        analysis: dict[str, Any],
        action: dict[str, Any],
    ) -> str | None:
        """
        Extract the actual source code from the retrieved chunk.

        Supports the common chunk representations used by the search
        pipeline without modifying the repository.
        """

        exact_change = self._extract_exact_code_change(action, analysis)
        if isinstance(exact_change, dict):
            old_code = exact_change.get("old_code")
            if isinstance(old_code, str) and old_code.strip():
                return old_code

        chunk = context.primary_chunk

        if not chunk:
            return None

        # Object-style chunk.
        for attribute in ("code", "content", "source_code", "text"):
            value = getattr(chunk, attribute, None)

            if isinstance(value, str) and value.strip():
                return value

        # Dict-style chunk.
        if isinstance(chunk, dict):
            for key in (
                "code",
                "content",
                "source_code",
                "text",
            ):
                value = chunk.get(key)

                if isinstance(value, str) and value.strip():
                    return value

        return None

    def _get_suggested_code(
        self,
        analysis: dict[str, Any],
        action: dict[str, Any],
    ) -> str | None:
        """
        Extract the LLM-generated replacement code.

        The complete suggested code should be supplied by the analysis
        stage. A textual change description is deliberately NOT converted
        into a fake patch.
        """

        exact_change = self._extract_exact_code_change(action, analysis)
        if isinstance(exact_change, dict):
            new_code = exact_change.get("new_code")
            if isinstance(new_code, str) and new_code.strip():
                return new_code

        candidates = [
            action.get("suggested_code"),
            action.get("proposed_code"),
            analysis.get("suggested_code"),
            analysis.get("proposed_code"),
        ]

        for value in candidates:
            if not isinstance(value, str):
                continue
            stripped = value.strip()
            if not stripped:
                continue

            if self._looks_like_code(stripped):
                return stripped

        return None

    @staticmethod
    def _looks_like_code(value: str) -> bool:
        """Reject prose-based explanations while accepting actual source snippets."""

        lowered = value.lower()
        if "\n" in value or "\r" in value:
            return True

        code_markers = (
            "def ",
            "class ",
            "if ",
            "for ",
            "while ",
            "return ",
            "print(",
            "raise ",
            "import ",
            "from ",
            "= ",
            "=>",
            "(",
            ")",
            "{",
            "}",
            "[",
            "]",
            ".",
            ":",
            "'",
            '"',
        )

        return any(marker in lowered for marker in code_markers)

    @staticmethod
    def _extract_exact_code_change(
        *sources: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Return the exact source-code change when an upstream stage provides one."""

        for source in sources:
            if not isinstance(source, dict):
                continue

            value = source.get("code_change")
            if isinstance(value, dict):
                return value

        return None

    def _normalize_code(self, code: str) -> str:
        """Normalize line endings while preserving source content."""

        return code.replace("\r\n", "\n").replace("\r", "\n").rstrip()

    def _build_test_suggestions(
        self,
        context: SearchContext,
    ) -> list[str]:
        intent = context.intent

        if intent == IntentType.FIX_BUG:
            return [
                "Run the relevant tests for the affected module.",
                "Add a regression test for the reported bug.",
                "Verify that valid inputs preserve existing behavior.",
            ]

        if intent == IntentType.ADD_FEATURE:
            return [
                "Add tests covering the new feature behavior.",
                "Run the relevant unit or integration tests.",
                "Verify backward compatibility with existing flows.",
            ]

        if intent == IntentType.OPTIMIZE:
            return [
                "Benchmark the affected code before and after the change.",
                "Verify the optimization preserves existing behavior.",
                "Run the relevant smoke tests.",
            ]

        if intent == IntentType.REFACTOR:
            return [
                "Run the existing tests before and after the refactoring.",
                "Confirm public interfaces remain unchanged.",
                "Check for regressions in the affected code path.",
            ]

        return [
            "Run the relevant tests for the affected area.",
            "Review the generated patch manually before applying it.",
        ]

