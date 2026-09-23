"""
app/modules/code_analysis/service/code_analysis_service.py

Service for coordinating code analysis and multi-layer validation.
"""

from __future__ import annotations

from typing import Any

from app.core.enums import IntentType
from app.modules.code_analysis.analyzers.add_feature_analyzer import (
    AddFeatureAnalyzer,
)
from app.modules.code_analysis.analyzers.fix_bug_analyzer import (
    FixBugAnalyzer,
)
from app.modules.code_analysis.analyzers.optimize_analyzer import (
    OptimizeAnalyzer,
)
from app.modules.code_analysis.analyzers.refactor_analyzer import (
    RefactorAnalyzer,
)
from app.modules.code_analysis.domain.analysis_domain import ValidationResult
from app.modules.code_analysis.validators.code_existence_validator import (
    CodeExistenceValidator,
)
from app.modules.code_analysis.validators.evidence_validator import (
    EvidenceValidator,
)
from app.modules.code_analysis.validators.suggestion_validator import (
    SuggestionValidator,
)
from app.modules.llm.service.llm_service import LLMService
from app.modules.search.domain.search_domain import (
    RetrievedChunk,
    SearchContext,
)


class CodeAnalysisService:
    def __init__(
        self,
        add_feature_analyzer: AddFeatureAnalyzer,
        fix_bug_analyzer: FixBugAnalyzer,
        optimize_analyzer: OptimizeAnalyzer,
        refactor_analyzer: RefactorAnalyzer,
        evidence_validator: EvidenceValidator,
        code_existence_validator: CodeExistenceValidator,
        suggestion_validator: SuggestionValidator,
        llm_service: LLMService | None = None,
    ) -> None:
        self.analyzers: dict[IntentType, Any] = {
            IntentType.ADD_FEATURE: add_feature_analyzer,
            IntentType.FIX_BUG: fix_bug_analyzer,
            IntentType.OPTIMIZE: optimize_analyzer,
            IntentType.REFACTOR: refactor_analyzer,
        }

        self.evidence_validator = evidence_validator
        self.code_existence_validator = code_existence_validator
        self.suggestion_validator = suggestion_validator

        self.llm_service = (
            llm_service
            or getattr(add_feature_analyzer, "llm_service", None)
        )

    async def analyze(self, context: SearchContext) -> dict[str, Any]:
        """
        Run intent-specific code analysis.

        RETRIEVE:
            Explain the retrieved code only.

        FIX_BUG / ADD_FEATURE / OPTIMIZE / REFACTOR:
            Delegate to the corresponding intent-specific analyzer.

        If LLM-based analysis fails, the error is propagated to
        CodeAnalysisStage, where the stage-level UNAVAILABLE fallback
        is created. This keeps failure handling centralized at the
        pipeline stage boundary.
        """

        if context.intent is None:
            raise ValueError(
                "Cannot perform code analysis without a classified intent."
            )

        # ---------------------------------------------------------
        # RETRIEVE
        # ---------------------------------------------------------
        #
        # RETRIEVE only explains existing code.
        # It must not generate:
        #   - proposed changes
        #   - suggested code
        #   - bug fixes
        #   - optimization recommendations
        #
        if context.intent == IntentType.RETRIEVE:
            ai_answer = await self._analyze_retrieve(context)

            primary_fp = (
                context.primary_chunk.file_path
                if context.primary_chunk
                else (
                    context.code_snippets[0].get("file_path")
                    if context.code_snippets
                    else None
                )
            )

            analysis: dict[str, Any] = {
                "intent": "RETRIEVE",
                "answer": ai_answer,
                "file_path": primary_fp,
                "symbol": context.target_symbol,
            }

            context.analysis_result = analysis
            return analysis

        # ---------------------------------------------------------
        # INTENT-SPECIFIC ANALYSIS
        # ---------------------------------------------------------

        analyzer = self.analyzers.get(context.intent)

        if analyzer is None:
            raise ValueError(
                f"No analyzer configured for intent: "
                f"{context.intent.value}"
            )

        try:
            result = await analyzer.analyze(context)

            if result is None:
                raise ValueError(
                    f"Analyzer returned no result for intent: "
                    f"{context.intent.value}"
                )

            analysis = getattr(result, "analysis", None)

            if not isinstance(analysis, dict):
                raise ValueError(
                    "Code analyzer returned an invalid analysis result. "
                    "Expected result.analysis to be a dictionary."
                )

            context.analysis_result = analysis

            return analysis

        except Exception as exc:
            # Do not invent an analysis when the LLM/analyzer fails.
            # Propagate the failure to CodeAnalysisStage, which owns
            # the deterministic UNAVAILABLE fallback.
            raise RuntimeError(
                f"Code analysis failed for intent "
                f"{context.intent.value}: {exc}"
            ) from exc

    def validate_analysis(
        self,
        analysis: dict[str, Any],
        chunks: list[RetrievedChunk],
    ) -> ValidationResult:
        """
        Validate the generated analysis against retrieved repository evidence.
        """

        evidence_result = self.evidence_validator.validate(
            analysis,
            chunks,
        )

        code_existence_result = self.code_existence_validator.validate(
            analysis,
            chunks,
        )

        suggestion_result = self.suggestion_validator.validate(
            analysis,
            chunks,
        )

        all_errors = (
            evidence_result.errors
            + code_existence_result.errors
            + suggestion_result.errors
        )

        is_valid = not all_errors

        return ValidationResult(
            is_valid=is_valid,
            status="passed" if is_valid else "failed",
            errors=all_errors,
        )

    async def _analyze_retrieve(
        self,
        context: SearchContext,
    ) -> str:
        """
        Generate a concise explanation for RETRIEVE queries.

        The response is based only on the retrieved repository context.
        No code modification or fix should be proposed here.

        If the LLM fails, the exception is propagated to
        CodeAnalysisStage so the stage-level fallback can be applied.
        """

        if not context.llm_context and not context.code_snippets:
            return (
                "No relevant code was found in the repository "
                "for this query."
            )

        user_prompt = (
            f"User Query:\n{context.query}\n\n"
            f"TOON-Encoded Repository Context:\n"
            f"{context.llm_context or '(No context)'}\n\n"
            f"The context above is encoded in TOON format: the metadata table "
            f"identifies each snippet by repository, file_path, function/class "
            f"name, and line range. Source code follows in CODE BLOCKS."
        )

        system_prompt = (
            "You are CodeLens, an expert software developer and "
            "codebase analyzer.\n"
            "Your task is to answer the user query based ONLY on the "
            "provided retrieved repository context.\n\n"
            "The repository Context is encoded in TOON (Token-Oriented Object "
            "Notation) format. TOON uses a compact tabular layout: the header row "
            "lists field names once, and each subsequent row is the corresponding "
            "comma-separated values for one code snippet. Fields: repository, "
            "file_path, function_name, class_name, chunk_type, start_line, "
            "end_line, language. The actual source code for each snippet "
            "follows in the CODE BLOCKS section.\n\n"
            "CRITICAL RULES:\n"
            "1. Base your answer only on the supplied repository context.\n"
            "2. Identify the relevant repository, file path, "
            "class/function name, and line range where the evidence exists.\n"
            "3. Explain the code clearly and directly answer the user query.\n"
            "4. NEVER invent, guess, or hallucinate files, functions, "
            "classes, or behavior not present in the context.\n"
            "5. If the retrieved context does not contain enough information "
            "to answer the query reliably, explicitly say so instead of "
            "hallucinating.\n"
            "6. This is a RETRIEVE request. Do NOT propose bug fixes, "
            "feature changes, refactoring, optimization, or replacement code "
            "unless the user explicitly asks for a modification.\n"
            "7. If multiple retrieved snippets contain the same function or "
            "method name, do not assume one is the target based on retrieval "
            "order, ranking, or any primary/relevance marker. Use the file "
            "path, class name, source code, and user query together to identify "
            "the relevant code. If the target cannot be determined reliably, "
            "state the ambiguity instead of guessing.\n"
            "8. The answer should focus on identifying and explaining the "
            "existing code."
        )

        llm = self.llm_service

        if not llm:
            return context.llm_context or "Code retrieved."

        try:
            response = await llm.provider.complete(
                prompt=user_prompt,
                system_prompt=system_prompt,
                max_tokens=2048,
                temperature=0.0,
            )

            return (
                response.text
                if hasattr(response, "text")
                else str(response)
            )

        except Exception as exc:
            # Important:
            # Do NOT return a fabricated/partial answer here.
            # Propagate the failure to CodeAnalysisStage so that it
            # creates the standard UNAVAILABLE fallback.
            raise RuntimeError(
                f"Retrieve code analysis failed: {exc}"
            ) from exc

