"""
app/modules/code_analysis/service/code_analysis_service.py
Service for coordinating code analysis.
"""

from typing import Any

from app.core.enums import IntentType
from app.modules.code_analysis.analyzers.add_feature_analyzer import AddFeatureAnalyzer
from app.modules.code_analysis.analyzers.fix_bug_analyzer import FixBugAnalyzer
from app.modules.code_analysis.analyzers.optimize_analyzer import OptimizeAnalyzer
from app.modules.code_analysis.analyzers.refactor_analyzer import RefactorAnalyzer
from app.modules.code_analysis.validators.code_existence_validator import CodeExistenceValidator
from app.modules.code_analysis.validators.evidence_validator import EvidenceValidator
from app.modules.code_analysis.validators.suggestion_validator import SuggestionValidator
from app.modules.search.domain.search_domain import SearchContext


class CodeAnalysisService:
    """Service for running intent-specific code analysis."""
    
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
        self.analyzers = {
            IntentType.ADD_FEATURE: add_feature_analyzer,
            IntentType.FIX_BUG: fix_bug_analyzer,
            IntentType.OPTIMIZE: optimize_analyzer,
            IntentType.REFACTOR: refactor_analyzer,
            IntentType.EXPLAIN: add_feature_analyzer, # Fallback
            IntentType.TEST_GENERATION: add_feature_analyzer, # Fallback
        }
        self.evidence_validator = evidence_validator
        self.code_existence_validator = code_existence_validator
        self.suggestion_validator = suggestion_validator

    async def analyze(self, context: SearchContext) -> dict[str, Any]:
        """Run the analysis and validate the output."""
        if not context.intent:
            return {"error": "No intent specified"}
            
        analyzer = self.analyzers.get(context.intent, self.analyzers[IntentType.ADD_FEATURE])
        result = await analyzer.analyze(context)
        
        # Run 3-layer validation
        ev_val = self.evidence_validator.validate(result.analysis, context.retrieved_chunks)
        ce_val = self.code_existence_validator.validate(result.analysis, context.retrieved_chunks)
        su_val = self.suggestion_validator.validate(result.analysis, context.retrieved_chunks)
        
        if not ev_val.is_valid or not ce_val.is_valid or not su_val.is_valid:
            # Handle validation failure (e.g., fallback, retry, or flag hallucination)
            result.analysis["hallucination_warning"] = True
            
        return result.analysis
