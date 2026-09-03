"""
app/modules/search/pipeline/evidence_validation.py
Pipeline stage: Evidence validation.
"""

from app.modules.search.domain.search_domain import SearchContext


class EvidenceValidationStage:
    async def execute(self, context: SearchContext) -> None:
        """Validate if we have enough evidence to proceed to LLM analysis."""
        if not context.retrieved_chunks:
            context.insufficient_evidence = True
