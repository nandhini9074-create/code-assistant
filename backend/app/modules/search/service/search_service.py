
"""
app/modules/search/service/search_service.py

Service layer for orchestrating the search pipeline.

Normal flow:
1. Request Validation
2. Intent Classification
3. Query Preprocessing
4. Collection Selection
5. Code Retrieval
6. Code Identification
7. Context Building
8. Code Analysis
9. Evidence Validation
10. Action Analysis
11. Suggestion Patch
12. Suggestion Validation
13. Final Triage
14. Response Generation

Deep Search:
- Only applies to FIX_BUG when deep_search_requested is True.
- The decision is made during IntentClassificationStage, before retrieval.
- CollectionSelectionStage resolves the Qdrant collection first.
- Deep Search replaces normal retrieval and analysis only for selected requests.
- Other requests retain the existing normal pipeline.
"""

from app.core.exceptions import RetrievalError
from app.core.logging import get_logger

from app.modules.search.domain.search_domain import (
    SearchContext,
    SearchResult,
)

from app.modules.search.pipeline.request_validation import (
    RequestValidationStage,
)
from app.modules.search.pipeline.intent_classification import (
    IntentClassificationStage,
)
from app.modules.search.pipeline.query_preprocessing import (
    QueryPreprocessingStage,
)
from app.modules.search.pipeline.collection_selection import (
    CollectionSelectionStage,
)
from app.modules.search.pipeline.code_retrieval import (
    CodeRetrievalStage,
)
from app.modules.search.pipeline.code_identification import (
    CodeIdentificationStage,
)
from app.modules.search.pipeline.deep_search import (
    DeepSearchStage,
)
from app.modules.search.pipeline.context_builder import (
    ContextBuilderStage,
)
from app.modules.search.pipeline.code_analysis import (
    CodeAnalysisStage,
)
from app.modules.search.pipeline.evidence_validation import (
    EvidenceValidationStage,
)
from app.modules.search.pipeline.action_analysis import (
    ActionAnalysisStage,
)
from app.modules.search.pipeline.suggestion_patch import (
    SuggestionPatchStage,
)
from app.modules.search.pipeline.suggestion_validation import (
    SuggestionValidationStage,
)
from app.modules.search.pipeline.final_triage import (
    FinalTriageStage,
)
from app.modules.search.pipeline.response_generation import (
    ResponseGenerationStage,
)

from app.core.enums import IntentType

logger = get_logger(__name__)


class SearchService:
    """Orchestrates normal search and conditional Deep Search."""

    def __init__(
        self,
        val_stage: RequestValidationStage,
        intent_stage: IntentClassificationStage,
        query_prep_stage: QueryPreprocessingStage,
        coll_sel_stage: CollectionSelectionStage,
        code_ret_stage: CodeRetrievalStage,
        code_ident_stage: CodeIdentificationStage,
        ctx_build_stage: ContextBuilderStage,
        code_analysis_stage: CodeAnalysisStage,
        ev_val_stage: EvidenceValidationStage,
        action_analysis_stage: ActionAnalysisStage,
        suggestion_patch_stage: SuggestionPatchStage,
        suggestion_validation_stage: SuggestionValidationStage,
        final_triage_stage: FinalTriageStage,
        resp_gen_stage: ResponseGenerationStage,
        deep_search_stage: DeepSearchStage | None = None,
    ) -> None:
        self.val_stage = val_stage
        self.intent_stage = intent_stage
        self.query_prep_stage = query_prep_stage
        self.coll_sel_stage = coll_sel_stage
        self.code_ret_stage = code_ret_stage
        self.code_ident_stage = code_ident_stage

        # Deep Search is optional and isolated from normal stages.
        # Do not pass unsupported dependencies to DeepSearchStage.
        self.deep_search_stage = (
            deep_search_stage
            if deep_search_stage is not None
            else DeepSearchStage()
        )

        self.ctx_build_stage = ctx_build_stage
        self.code_analysis_stage = code_analysis_stage
        self.ev_val_stage = ev_val_stage
        self.action_analysis_stage = action_analysis_stage
        self.suggestion_patch_stage = suggestion_patch_stage
        self.suggestion_validation_stage = suggestion_validation_stage
        self.final_triage_stage = final_triage_stage
        self.resp_gen_stage = resp_gen_stage

        # Preserve the existing normal-stage list and ordering.
        # DeepSearchStage is not included in this list.
        self.normal_stages = [
            self.query_prep_stage,
            self.code_ret_stage,
            self.code_ident_stage,
            self.ctx_build_stage,
            self.code_analysis_stage,
            self.ev_val_stage,
            self.action_analysis_stage,
            self.suggestion_patch_stage,
            self.suggestion_validation_stage,
            self.final_triage_stage,
        ]

    @staticmethod
    def _deep_search_selected(context: SearchContext) -> bool:
        """Select Deep Search only for an explicitly selected FIX_BUG."""
        if context.intent != IntentType.FIX_BUG:
            return False

        parameters = context.intent_parameters or {}

        return (
            isinstance(parameters, dict)
            and parameters.get("deep_search_requested") is True
        )

    async def _execute_stage(
        self,
        stage: object,
        context: SearchContext,
        stage_number: int,
    ) -> bool:
        """
        Execute one stage.

        Returns False when an early exit prevents further stage execution.
        """
        stage_name = type(stage).__name__
        early_exit_before = context.early_exit

        logger.info(
            "search_stage_started",
            stage_number=stage_number,
            stage=stage_name,
            repo_name=context.repo_name,
            early_exit=context.early_exit,
        )

        if context.early_exit:
            logger.info(
                "search_stage_skipped",
                stage_number=stage_number,
                stage=stage_name,
                reason=context.early_exit,
            )
            return False

        try:
            await stage.execute(context)

            logger.info(
                "search_stage_completed",
                stage_number=stage_number,
                stage=stage_name,
                repo_name=context.repo_name,
                early_exit=context.early_exit,
            )

            if context.early_exit and not early_exit_before:
                logger.warning(
                    "search_pipeline_early_exit",
                    stage_number=stage_number,
                    stage=stage_name,
                    repo_name=context.repo_name,
                    early_exit=context.early_exit,
                )

            return not bool(context.early_exit)

        except Exception as exc:
            logger.exception(
                "search_stage_failed",
                stage_number=stage_number,
                stage=stage_name,
                repo_name=context.repo_name,
                error=str(exc),
            )

            if isinstance(stage, CodeAnalysisStage):
                context.analysis_result = (
                    stage._build_fallback_analysis(
                        context,
                        "Code analysis was unavailable.",
                    )
                )
                context.validated = False
                context.validation_status = "unavailable"
                return True

            raise RetrievalError(
                f"Search stage '{stage_name}' failed: {exc}"
            ) from exc

    async def run_pipeline(
        self,
        source_type: str,
        source_location: str,
        query: str,
    ) -> SearchResult:
        context = SearchContext(
            source_type=source_type,
            source_location=source_location,
            query=query,
        )

        logger.info(
            "search_pipeline_started",
            source_type=source_type,
            source_location=source_location,
            query=query,
        )

        try:
            # 1. Request validation
            await self._execute_stage(
                self.val_stage,
                context,
                1,
            )

            if context.early_exit:
                return await self._generate_response(context)

            # 2. Intent classification and Deep Search decision
            await self._execute_stage(
                self.intent_stage,
                context,
                2,
            )

            if context.early_exit:
                return await self._generate_response(context)

            deep_search_selected = self._deep_search_selected(context)

            logger.info(
                "search_mode_selected",
                repo_name=context.repo_name,
                intent=(
                    context.intent.value
                    if context.intent is not None
                    else None
                ),
                mode=(
                    "DEEP_SEARCH"
                    if deep_search_selected
                    else "NORMAL_SEARCH"
                ),
                reason=(context.intent_parameters or {}).get(
                    "deep_search_reason"
                ),
            )

            # 3. Query preprocessing
            await self._execute_stage(
                self.query_prep_stage,
                context,
                3,
            )

            if context.early_exit:
                return await self._generate_response(context)

            # 4. Collection selection
            await self._execute_stage(
                self.coll_sel_stage,
                context,
                4,
            )

            if context.early_exit:
                return await self._generate_response(context)

            if not context.qdrant_collection:
                context.early_exit = "EARLY_EXIT_A"
                context.early_exit_message = (
                    "No Qdrant collection was resolved for "
                    f"repository '{context.repo_name}'."
                )
                return await self._generate_response(context)

            # 5. Deep Search branch.
            # This runs before normal code retrieval and replaces the
            # normal retrieval/analysis path only for selected requests.
            if deep_search_selected:
                logger.info(
                    "deep_search_branch_started",
                    repo_name=context.repo_name,
                    collection=context.qdrant_collection,
                )

                await self._execute_stage(
                    self.deep_search_stage,
                    context,
                    5,
                )

                # Check the actual result before interpreting early_exit.
                # DeepSearchStage intentionally sets early_exit after its
                # workflow returns, including for incomplete/unavailable
                # terminal results.
                result = context.deep_search_result

                if not isinstance(result, dict):
                    context.early_exit = "DEEP_SEARCH_UNAVAILABLE"
                    context.early_exit_message = (
                        "Deep Search did not produce a usable investigation "
                        "result. No root cause or fix will be assumed."
                    )

                    return await self._generate_response(context)

                result_status = result.get("status")

                if result_status not in {
                    "complete",
                    "incomplete",
                    "unavailable",
                }:
                    context.early_exit = "DEEP_SEARCH_UNAVAILABLE"
                    context.early_exit_message = (
                        "Deep Search returned an unrecognized result status. "
                        "No root cause or fix will be assumed."
                    )

                    return await self._generate_response(context)

                # Do not execute normal retrieval/analysis stages after
                # Deep Search. ResponseGenerationStage must handle the
                # deep_search_result and present its actual status.
                return await self._generate_response(context)

            # 6. Normal pipeline.
            # Keep the existing stage list, ordering, and error behavior.
            stage_number = 5

            for stage in self.normal_stages:
                should_continue = await self._execute_stage(
                    stage,
                    context,
                    stage_number,
                )
                stage_number += 1

                if not should_continue:
                    break

            return await self._generate_response(context)

        except RetrievalError as exc:
            logger.error(
                "search_pipeline_retrieval_error",
                source_location=source_location,
                error=str(exc),
            )

            return SearchResult(
                success=True,
                response=ResponseGenerationStage.build_failure_response(
                    context,
                    exc,
                ),
            )

        except Exception as exc:
            logger.exception(
                "search_pipeline_unexpected_error",
                source_location=source_location,
                error=str(exc),
            )

            return SearchResult(
                success=True,
                response=ResponseGenerationStage.build_failure_response(
                    context,
                    exc,
                ),
            )

    async def _generate_response(
        self,
        context: SearchContext,
    ) -> SearchResult:
        """Generate the final response, including early-exit responses."""
        try:
            await self.resp_gen_stage.execute(context)
        except Exception as exc:
            logger.exception(
                "response_generation_stage_failed",
                repo_name=context.repo_name,
                error=str(exc),
            )

            context.final_response = (
                self.resp_gen_stage.build_failure_response(
                    context,
                    exc,
                )
            )

        return SearchResult(
            success=True,
            response=context.final_response,
        )
