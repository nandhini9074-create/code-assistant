
"""
app/modules/search/service/search_service.py

Service layer for orchestrating the complete 13-stage search pipeline.

Stages are run in order; if context.early_exit is set by any stage,
the pipeline skips remaining processing stages and jumps directly to
response generation.
"""

from app.core.exceptions import RetrievalError
from app.core.logging import get_logger
from app.modules.search.domain.search_domain import SearchContext, SearchResult
from app.modules.search.pipeline.action_analysis import ActionAnalysisStage
from app.modules.search.pipeline.code_analysis import CodeAnalysisStage
from app.modules.search.pipeline.code_identification import CodeIdentificationStage
from app.modules.search.pipeline.code_retrieval import CodeRetrievalStage
from app.modules.search.pipeline.collection_selection import CollectionSelectionStage
from app.modules.search.pipeline.context_builder import ContextBuilderStage
from app.modules.search.pipeline.evidence_validation import EvidenceValidationStage
from app.modules.search.pipeline.final_triage import FinalTriageStage
from app.modules.search.pipeline.intent_classification import IntentClassificationStage
from app.modules.search.pipeline.query_preprocessing import QueryPreprocessingStage
from app.modules.search.pipeline.repository_identification import RepositoryIdentificationStage
from app.modules.search.pipeline.request_validation import RequestValidationStage
from app.modules.search.pipeline.response_generation import ResponseGenerationStage


logger = get_logger(__name__)


# Stages that are always run regardless of early-exit state
_ALWAYS_RUN = {
    RequestValidationStage,
    ResponseGenerationStage,
}


class SearchService:
    """Orchestrates the 13-stage search pipeline."""

    def __init__(
        self,
        val_stage: RequestValidationStage,
        intent_stage: IntentClassificationStage,
        query_prep_stage: QueryPreprocessingStage,
        repo_ident_stage: RepositoryIdentificationStage,
        coll_sel_stage: CollectionSelectionStage,
        code_ret_stage: CodeRetrievalStage,
        code_ident_stage: CodeIdentificationStage,
        ctx_build_stage: ContextBuilderStage,
        code_analysis_stage: CodeAnalysisStage,
        ev_val_stage: EvidenceValidationStage,
        action_analysis_stage: ActionAnalysisStage,
        final_triage_stage: FinalTriageStage,
        resp_gen_stage: ResponseGenerationStage,
    ) -> None:

        self.val_stage = val_stage
        self.intent_stage = intent_stage
        self.query_prep_stage = query_prep_stage
        self.repo_ident_stage = repo_ident_stage
        self.coll_sel_stage = coll_sel_stage
        self.code_ret_stage = code_ret_stage
        self.code_ident_stage = code_ident_stage
        self.ctx_build_stage = ctx_build_stage
        self.code_analysis_stage = code_analysis_stage
        self.ev_val_stage = ev_val_stage
        self.action_analysis_stage = action_analysis_stage
        self.final_triage_stage = final_triage_stage
        self.resp_gen_stage = resp_gen_stage

        self.stages = [
            self.val_stage,
            self.intent_stage,
            self.query_prep_stage,
            self.repo_ident_stage,
            self.coll_sel_stage,
            self.code_ret_stage,
            self.code_ident_stage,
            self.ctx_build_stage,
            self.code_analysis_stage,
            self.ev_val_stage,
            self.action_analysis_stage,
            self.final_triage_stage,
            self.resp_gen_stage,
        ]

    async def run_pipeline(
        self,
        repo_id: str,
        query: str,
    ) -> SearchResult:
        """
        Execute the 13-stage search pipeline.

        When context.early_exit is set by any stage,
        intermediate processing stages are skipped and
        execution jumps directly to ResponseGenerationStage.
        """

        context = SearchContext(
            repo_id=repo_id,
            query=query,
        )

        # =========================================================
        # PIPELINE START
        # =========================================================

        logger.info(
            "search_pipeline_started",
            repo_id=repo_id,
            query=query,
            total_stages=len(self.stages),
        )

        try:

            for index, stage in enumerate(self.stages, start=1):

                stage_name = stage.__class__.__name__

                # =================================================
                # STAGE START
                # =================================================

                logger.info(
                    "search_stage_started",
                    stage_number=index,
                    stage=stage_name,
                    repo_id=context.repo_id,
                    early_exit=context.early_exit,
                )

                print("\n========================================")
                print(
                    f"STAGE {index}/{len(self.stages)}:",
                    stage_name,
                )
                print(
                    "EARLY EXIT BEFORE STAGE:",
                    context.early_exit,
                )
                print("REPO ID:", context.repo_id)
                print("QUERY:", context.query)
                print("========================================")

                # =================================================
                # EARLY EXIT CHECK
                # =================================================

                if (
                    context.early_exit
                    and type(stage) not in _ALWAYS_RUN
                ):

                    logger.info(
                        "search_stage_skipped",
                        stage_number=index,
                        stage=stage_name,
                        repo_id=context.repo_id,
                        early_exit=context.early_exit,
                        reason="early_exit_already_set",
                    )

                    print(
                        "[SKIP] STAGE SKIPPED:",
                        stage_name,
                    )
                    print(
                        "REASON:",
                        context.early_exit,
                    )

                    continue

                # =================================================
                # STAGE EXECUTION
                # =================================================

                logger.info(
                    "search_stage_executing",
                    stage_number=index,
                    stage=stage_name,
                    repo_id=context.repo_id,
                )

                print(
                    "[RUN] RUNNING:",
                    stage_name,
                )

                try:

                    await stage.execute(context)

                    # =============================================
                    # STAGE COMPLETED
                    # =============================================

                    logger.info(
                        "search_stage_completed",
                        stage_number=index,
                        stage=stage_name,
                        repo_id=context.repo_id,
                        early_exit=context.early_exit,
                    )

                    print(
                        "[OK] COMPLETED:",
                        stage_name,
                    )
                    print(
                        "EARLY EXIT AFTER STAGE:",
                        context.early_exit,
                    )

                    # =============================================
                    # EARLY EXIT DETECTED
                    # =============================================

                    if context.early_exit:

                        logger.warning(
                            "search_pipeline_early_exit_set",
                            stage_number=index,
                            stage=stage_name,
                            repo_id=context.repo_id,
                            early_exit=context.early_exit,
                            message=context.early_exit_message,
                        )

                        print(
                            "[WARN] EARLY EXIT SET BY:",
                            stage_name,
                        )
                        print(
                            "EARLY EXIT CODE:",
                            context.early_exit,
                        )
                        print(
                            "EARLY EXIT MESSAGE:",
                            context.early_exit_message,
                        )

                # ================================================
                # STAGE FAILURE
                # ================================================

                except Exception as exc:

                    logger.exception(
                        "search_pipeline_stage_failed",
                        stage_number=index,
                        stage=stage_name,
                        repo_id=context.repo_id,
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )

                    print(
                        "\n[ERROR] STAGE FAILED:",
                        stage_name,
                    )
                    print(
                        "EXCEPTION TYPE:",
                        type(exc).__name__,
                    )
                    print(
                        "EXCEPTION:",
                        str(exc),
                    )

                    raise RetrievalError(
                        f"Pipeline stage {stage_name} failed: {exc}"
                    )

            # =====================================================
            # PIPELINE COMPLETED
            # =====================================================

            logger.info(
                "search_pipeline_completed",
                repo_id=repo_id,
                early_exit=context.early_exit,
                has_final_response=(
                    context.final_response is not None
                ),
            )

            print(
                "\n========== SEARCH PIPELINE COMPLETED =========="
            )
            print(
                "FINAL EARLY EXIT:",
                context.early_exit,
            )
            print(
                "HAS FINAL RESPONSE:",
                context.final_response is not None,
            )

            return SearchResult(
                success=True,
                response=context.final_response,
            )

        # =========================================================
        # RETRIEVAL ERROR
        # =========================================================

        except RetrievalError as exc:

            logger.error(
                "search_pipeline_retrieval_error",
                repo_id=repo_id,
                error=str(exc),
            )

            return SearchResult(
                success=False,
                error_message=str(exc),
            )

        # =========================================================
        # UNEXPECTED ERROR
        # =========================================================

        except Exception as exc:

            logger.exception(
                "search_pipeline_failed",
                repo_id=repo_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )

            return SearchResult(
                success=False,
                error_message="Internal search error",
            )

