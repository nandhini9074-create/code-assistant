
"""
app/modules/search/pipeline/code_analysis.py

Pipeline stage: Intent-Specific Code Analysis (Step 9).

Dispatches code analysis to the analyzer corresponding to the
classified intent and stores the resulting analysis in the
SearchContext.

Validation is handled separately by Step 10.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.modules.code_analysis.service.code_analysis_service import (
    CodeAnalysisService,
)
from app.modules.search.domain.search_domain import SearchContext

logger = get_logger(__name__)


class CodeAnalysisStage:
    """Pipeline stage responsible for intent-specific code analysis."""

    def __init__(self, code_analysis_service: CodeAnalysisService) -> None:
        self.code_analysis_service = code_analysis_service

    async def execute(self, context: SearchContext) -> None:
        """
        Execute intent-specific code analysis.

        Step 9 only performs analysis. Validation of the generated
        analysis is handled by the separate Step 10 validation stage.
        """

        # Respect pipeline early-exit decisions from previous stages.
        if context.early_exit:
            logger.info(
                "code_analysis_stage_skipped",
                reason=context.early_exit,
                repo_id=context.repo_id,
            )
            return

        # Step 9 requires a classified intent.
        if context.intent is None:
            raise ValueError(
                "Cannot perform code analysis without a classified intent."
            )

        logger.info(
            "code_analysis_stage_starting",
            intent=context.intent.value,
            repo_id=context.repo_id,
        )

        # CodeAnalysisService selects the correct analyzer based on
        # context.intent and executes it against the current context.
        print("\n" + "=" * 80)
        print("LLM INPUT")
        print("=" * 80)

        print("\nQUERY:")
        print(context.query)

        print("\nCODE CONTEXT:")
        print(context.llm_context or "EMPTY")

        print("=" * 80 + "\n")

        analysis = await self.code_analysis_service.analyze(context)

        # Store the result in the shared pipeline context.
        context.analysis_result = analysis

        logger.info(
            "code_analysis_stage_complete",
            intent=context.intent.value,
            repo_id=context.repo_id,
            keys=list(analysis.keys()),
        )

