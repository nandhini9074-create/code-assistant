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
from app.modules.search.domain.search_domain import (
    RetrievedChunk,
    SearchContext,
)


class CodeAnalysisService:
    """Service for running intent-specific code analysis and validation."""

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
        """Initialize analyzers and validators."""

        self.analyzers: dict[IntentType, Any] = {
            IntentType.ADD_FEATURE: add_feature_analyzer,
            IntentType.FIX_BUG: fix_bug_analyzer,
            IntentType.OPTIMIZE: optimize_analyzer,
            IntentType.REFACTOR: refactor_analyzer,
        }

        self.evidence_validator = evidence_validator
        self.code_existence_validator = code_existence_validator
        self.suggestion_validator = suggestion_validator
        self.llm_service = llm_service or getattr(add_feature_analyzer, "llm_service", None)

    async def analyze(self, context: SearchContext) -> dict[str, Any]:
        """
        Run the analyzer corresponding to the classified intent.

        The intent must already have been classified by an earlier
        pipeline stage. This method does not guess a default intent.

        For RETRIEVE intent, generate an AI answer based strictly on
        User Query and Retrieved Repository Context.
        """

        if context.intent is None:
            raise ValueError(
                "Cannot perform code analysis without a classified intent."
            )

        # RETRIEVE intent: LLM grounded answer based only on retrieved context
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
                "suggestion": ai_answer,
                "current_behavior": ai_answer,
                "proposed_change": ai_answer,
                "file_path": primary_fp,
                "symbol": context.target_symbol,
            }
            context.analysis_result = analysis
            return analysis

        analyzer = self.analyzers.get(context.intent)

        if analyzer is None:
            raise ValueError(
                f"No analyzer configured for intent: {context.intent.value}"
            )

        result = await analyzer.analyze(context)

        if result is None:
            raise ValueError(
                f"Analyzer returned no result for intent: {context.intent.value}"
            )

        analysis = getattr(result, "analysis", None)

        if not isinstance(analysis, dict):
            raise ValueError(
                "Code analyzer returned an invalid analysis result. "
                "Expected result.analysis to be a dictionary."
            )

        context.analysis_result = analysis

        return analysis


    def validate_analysis(
        self,
        analysis: dict[str, Any],
        chunks: list[RetrievedChunk],
    ) -> ValidationResult:
        """
        Run the three-layer validation on the analysis.

        Validation layers:
        1. Evidence validation
        2. Code existence validation
        3. Suggestion validation
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

    async def _analyze_retrieve(self, context: SearchContext) -> str:
        """
        Generate grounded AI answer for RETRIEVE intent based strictly on
        the supplied repository context.
        """
        if not context.llm_context and not context.code_snippets:
            return "No relevant code was found in the repository for this query."

        user_prompt = (
            f"User Query:\n{context.query}\n\n"
            f"Retrieved Repository Context:\n{context.llm_context or '(No context)'}"
        )
        system_prompt = (
            "You are CodeLens, an expert software developer and codebase analyzer.\n"
            "Your task is to answer the user query based ONLY on the provided retrieved repository context.\n\n"
            "CRITICAL RULES:\n"
            "1. Base your answer only on the supplied repository context.\n"
            "2. Identify the relevant repository, file path, class/function name, and line range where the evidence exists.\n"
            "3. Explain the code clearly and directly answer the user query.\n"
            "4. NEVER invent, guess, or hallucinate files, functions, classes, or behavior not in the context.\n"
            "5. If the retrieved context does not contain enough information to answer the query reliably, explicitly say so instead of hallucinating."
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
            return response.text if hasattr(response, "text") else str(response)
        except Exception as exc:
            return f"Code identified in repository: {context.target_symbol or 'target'} ({exc})"
