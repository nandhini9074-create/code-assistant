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

    async def analyze(self, context: SearchContext) -> dict[str, Any]:
        """
        Run the analyzer corresponding to the classified intent.

        The intent must already have been classified by an earlier
        pipeline stage. This method does not guess a default intent.
        """

        if context.intent is None:
            raise ValueError(
                "Cannot perform code analysis without a classified intent."
            )

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
