"""
app/modules/search/service/search_service.py
Service layer for orchestrating the search pipeline.
"""

from app.core.exceptions import RetrievalError
from app.core.logging import get_logger
from app.modules.search.domain.search_domain import SearchContext, SearchResult
from app.modules.search.pipeline.code_identification import CodeIdentificationStage
from app.modules.search.pipeline.code_retrieval import CodeRetrievalStage
from app.modules.search.pipeline.collection_selection import CollectionSelectionStage
from app.modules.search.pipeline.context_builder import ContextBuilderStage
from app.modules.search.pipeline.evidence_validation import EvidenceValidationStage
from app.modules.search.pipeline.intent_classification import IntentClassificationStage
from app.modules.search.pipeline.query_preprocessing import QueryPreprocessingStage
from app.modules.search.pipeline.repository_identification import RepositoryIdentificationStage
from app.modules.search.pipeline.request_validation import RequestValidationStage
from app.modules.search.pipeline.response_generation import ResponseGenerationStage

logger = get_logger(__name__)


class SearchService:
    """Orchestrates the search pipeline."""
    
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
        ev_val_stage: EvidenceValidationStage,
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
        self.ev_val_stage = ev_val_stage
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
            self.ev_val_stage,
            self.resp_gen_stage,
        ]

    async def run_pipeline(self, repo_id: str, query: str) -> SearchResult:
        """Executes the search pipeline."""
        context = SearchContext(repo_id=repo_id, query=query)
        
        try:
            for i, stage in enumerate(self.stages):
                stage_name = stage.__class__.__name__
                try:
                    await stage.execute(context)
                except Exception as exc:
                    logger.error("search_pipeline_stage_failed", stage=stage_name, repo_id=repo_id, exc_info=exc)
                    raise RetrievalError(f"Pipeline stage {stage_name} failed: {str(exc)}")
                    
            return SearchResult(success=True, response=context.final_response)
            
        except RetrievalError as exc:
            return SearchResult(success=False, error_message=str(exc))
        except Exception as exc:
            logger.error("search_pipeline_failed", repo_id=repo_id, exc_info=exc)
            return SearchResult(success=False, error_message="Internal search error")
