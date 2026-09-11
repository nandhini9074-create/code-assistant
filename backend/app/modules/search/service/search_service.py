"""
app/modules/search/service/search_service.py

Service layer for orchestrating the search pipeline.

The search pipeline uses the repository name supplied in the request
and does not perform PostgreSQL-based repository identification.

Pipeline:
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
11. Final Triage
12. Response Generation
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
from app.modules.search.pipeline.final_triage import (
    FinalTriageStage,
)
from app.modules.search.pipeline.response_generation import (
    ResponseGenerationStage,
)


logger = get_logger(__name__)


# These stages should always execute so that the request can be
# validated and a final response can be generated even when an
# earlier stage sets an early-exit condition.
_ALWAYS_RUN = {
    RequestValidationStage,
    ResponseGenerationStage,
}


class SearchService:

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
        final_triage_stage: FinalTriageStage,
        resp_gen_stage: ResponseGenerationStage,
    ) -> None:

        self.val_stage = val_stage
        self.intent_stage = intent_stage
        self.query_prep_stage = query_prep_stage
        self.coll_sel_stage = coll_sel_stage
        self.code_ret_stage = code_ret_stage
        self.code_ident_stage = code_ident_stage
        self.ctx_build_stage = ctx_build_stage
        self.code_analysis_stage = code_analysis_stage
        self.ev_val_stage = ev_val_stage
        self.action_analysis_stage = action_analysis_stage
        self.final_triage_stage = final_triage_stage
        self.resp_gen_stage = resp_gen_stage

        # ---------------------------------------------------------
        # Search pipeline
        # ---------------------------------------------------------
        #
        # RepositoryIdentificationStage has intentionally been
        # removed.
        #
        # repo_name is already supplied to run_pipeline() and is
        # passed directly into SearchContext.
        #
        # CollectionSelectionStage is responsible for mapping
        # repo_name -> Qdrant collection.
        #
        # ---------------------------------------------------------

        self.stages = [
            self.val_stage,              # 1
            self.intent_stage,           # 2
            self.query_prep_stage,       # 3
            self.coll_sel_stage,         # 4
            self.code_ret_stage,         # 5
            self.code_ident_stage,       # 6
            self.ctx_build_stage,        # 7
            self.code_analysis_stage,    # 8
            self.ev_val_stage,           # 9
            self.action_analysis_stage,  # 10
            self.final_triage_stage,     # 11
            self.resp_gen_stage,         # 12
        ]

    async def run_pipeline(
        self,
        repo_name: str,
        query: str,
    ) -> SearchResult:

        # ---------------------------------------------------------
        # Create search context
        # ---------------------------------------------------------
        #
        # repo_name comes directly from the API request.
        #
        # Do NOT perform repository lookup through PostgreSQL here.
        #
        # repo_id is intentionally not supplied because the search
        # pipeline uses repo_name + Qdrant collection.
        #
        # ---------------------------------------------------------

        context = SearchContext(
            repo_name=repo_name,
            query=query,
        )

        logger.info(
            "search_pipeline_started",
            repo_name=repo_name,
            query=query,
            total_stages=len(self.stages),
        )

        try:

            # -----------------------------------------------------
            # Execute stages sequentially
            # -----------------------------------------------------

            for index, stage in enumerate(self.stages, start=1):

                stage_name = stage.__class__.__name__

                logger.info(
                    "search_stage_started",
                    stage_number=index,
                    stage=stage_name,
                    repo_name=context.repo_name,
                    early_exit=context.early_exit,
                )


                # -------------------------------------------------
                # Skip remaining processing stages if an early
                # exit was already triggered.
                #
                # ResponseGenerationStage is still executed so
                # that the user receives a proper response.
                # -------------------------------------------------

                if (
                    context.early_exit
                    and type(stage) not in _ALWAYS_RUN
                ):
                    logger.info(
                        "search_stage_skipped",
                        stage_number=index,
                        stage=stage_name,
                        reason="early_exit",
                    )

                    continue

                # -------------------------------------------------
                # Execute current stage
                # -------------------------------------------------

                logger.info(
                    "search_stage_executing",
                    stage_number=index,
                    stage=stage_name,
                    repo_name=context.repo_name,
                )

                try:

                    await stage.execute(context)

                    logger.info(
                        "search_stage_completed",
                        stage_number=index,
                        stage=stage_name,
                        repo_name=context.repo_name,
                        early_exit=context.early_exit,
                    )


                    # ---------------------------------------------
                    # Log early exit if this stage triggered one.
                    # ---------------------------------------------

                    if context.early_exit:

                        logger.warning(
                            "search_pipeline_early_exit",
                            stage_number=index,
                            stage=stage_name,
                            repo_name=context.repo_name,
                            early_exit=context.early_exit,
                        )


                except Exception as exc:

                    logger.exception(
                        "search_stage_failed",
                        stage_number=index,
                        stage=stage_name,
                        repo_name=context.repo_name,
                        error=str(exc),
                    )

                    raise RetrievalError(
                        f"Search stage '{stage_name}' failed: {exc}"
                    ) from exc

            # -----------------------------------------------------
            # Pipeline completed
            # -----------------------------------------------------

            logger.info(
                "search_pipeline_completed",
                repo_name=context.repo_name,
                early_exit=context.early_exit,
            )

            return SearchResult(
                success=True,
                response=context.final_response,
            )

        except RetrievalError as exc:

            logger.error(
                "search_pipeline_retrieval_error",
                repo_name=repo_name,
                error=str(exc),
            )

            return SearchResult(
                success=False,
                error_message=str(exc),
            )

        except Exception as exc:

            logger.exception(
                "search_pipeline_unexpected_error",
                repo_name=repo_name,
                error=str(exc),
            )

            return SearchResult(
                success=False,
                error_message="Internal search error",
            )