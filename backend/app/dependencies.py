"""
app/dependencies.py
FastAPI dependency injection providers for all services.
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.session import get_db
from app.modules.jobs.repository.job_repository import JobRepository
from app.modules.jobs.service.job_service import JobService
from app.modules.repositories.repository.repository_repo import RepositoryRepository
from app.modules.repositories.service.repository_service import RepositoryService
from app.modules.webhooks.validators.webhook_validator import WebhookValidator
from app.modules.webhooks.service.webhook_service import WebhookService
from app.modules.ingestion.repository.ingestion_job_repo import IngestionJobRepository


def get_repository_repo(session: AsyncSession = Depends(get_db)) -> RepositoryRepository:
    return RepositoryRepository(session)


def get_ingestion_job_repo(session: AsyncSession = Depends(get_db)) -> IngestionJobRepository:
    return IngestionJobRepository(session)


def get_repository_service(
    repo_repo: RepositoryRepository = Depends(get_repository_repo),
) -> RepositoryService:
    return RepositoryService(repo_repo)


def get_job_repository(session: AsyncSession = Depends(get_db)) -> JobRepository:
    return JobRepository(session)


def get_job_service(
    job_repo: JobRepository = Depends(get_job_repository),
) -> JobService:
    return JobService(job_repo)


def get_webhook_validator(
    repo_repo: RepositoryRepository = Depends(get_repository_repo),
) -> WebhookValidator:
    return WebhookValidator(repo_repo)


def get_webhook_service(
    validator: WebhookValidator = Depends(get_webhook_validator),
    job_repo: IngestionJobRepository = Depends(get_ingestion_job_repo),
) -> WebhookService:
    return WebhookService(validator, job_repo)


def get_llm_provider():
    from app.modules.llm.providers.groq_provider import GroqProvider
    return GroqProvider()


def get_llm_service(
    provider=Depends(get_llm_provider),
):
    from app.modules.llm.service.llm_service import LLMService
    return LLMService(provider)

def get_query_understanding_service(
    llm_service=Depends(get_llm_service),
):
    from app.modules.search.pipeline.intent_classification import IntentClassificationStage
    from app.modules.search.pipeline.query_preprocessing import QueryPreprocessingStage
    from app.modules.search.pipeline.request_validation import RequestValidationStage
    from app.modules.search.service.query_understanding_service import QueryUnderstandingService

    return QueryUnderstandingService(
        val_stage=RequestValidationStage(),
        intent_stage=IntentClassificationStage(llm_service),
        query_prep_stage=QueryPreprocessingStage(llm_service),
    )



def get_code_analysis_service(
    llm_service=Depends(get_llm_service),
):
    from app.modules.code_analysis.analyzers.add_feature_analyzer import AddFeatureAnalyzer
    from app.modules.code_analysis.analyzers.fix_bug_analyzer import FixBugAnalyzer
    from app.modules.code_analysis.analyzers.optimize_analyzer import OptimizeAnalyzer
    from app.modules.code_analysis.analyzers.refactor_analyzer import RefactorAnalyzer
    from app.modules.code_analysis.service.code_analysis_service import CodeAnalysisService
    from app.modules.code_analysis.validators.code_existence_validator import CodeExistenceValidator
    from app.modules.code_analysis.validators.evidence_validator import EvidenceValidator
    from app.modules.code_analysis.validators.suggestion_validator import SuggestionValidator

    return CodeAnalysisService(
        add_feature_analyzer=AddFeatureAnalyzer(llm_service),
        fix_bug_analyzer=FixBugAnalyzer(llm_service),
        optimize_analyzer=OptimizeAnalyzer(llm_service),
        refactor_analyzer=RefactorAnalyzer(llm_service),
        evidence_validator=EvidenceValidator(),
        code_existence_validator=CodeExistenceValidator(),
        suggestion_validator=SuggestionValidator(),
    )


def get_search_service(
    repo_repo: RepositoryRepository = Depends(get_repository_repo),
    llm_service=Depends(get_llm_service),
    code_analysis_service=Depends(get_code_analysis_service),
):
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
    from app.modules.search.retrieval.dense_search import DenseSearch
    from app.modules.search.retrieval.hybrid_search import HybridSearch
    from app.modules.search.retrieval.reranker import Reranker
    from app.modules.search.retrieval.result_merger import ResultMerger
    from app.modules.search.retrieval.sparse_search import SparseSearch
    from app.modules.search.service.search_service import SearchService

    val_stage = RequestValidationStage()
    intent_stage = IntentClassificationStage(llm_service)
    query_prep_stage = QueryPreprocessingStage(llm_service)
    repo_ident_stage = RepositoryIdentificationStage(repo_repo)
    coll_sel_stage = CollectionSelectionStage()

    dense = DenseSearch()
    sparse = SparseSearch()
    merger = ResultMerger()
    reranker = Reranker()
    hybrid = HybridSearch(dense=dense, sparse=sparse, merger=merger, reranker=reranker)
    code_ret_stage = CodeRetrievalStage(hybrid)

    code_ident_stage = CodeIdentificationStage(llm_service, code_ret_stage=code_ret_stage)
    ctx_build_stage = ContextBuilderStage()
    code_analysis_stage = CodeAnalysisStage(code_analysis_service)
    ev_val_stage = EvidenceValidationStage(code_analysis_service)
    action_analysis_stage = ActionAnalysisStage()
    final_triage_stage = FinalTriageStage()
    resp_gen_stage = ResponseGenerationStage(llm_service)

    return SearchService(
        val_stage=val_stage,
        intent_stage=intent_stage,
        query_prep_stage=query_prep_stage,
        repo_ident_stage=repo_ident_stage,
        coll_sel_stage=coll_sel_stage,
        code_ret_stage=code_ret_stage,
        code_ident_stage=code_ident_stage,
        ctx_build_stage=ctx_build_stage,
        code_analysis_stage=code_analysis_stage,
        ev_val_stage=ev_val_stage,
        action_analysis_stage=action_analysis_stage,
        final_triage_stage=final_triage_stage,
        resp_gen_stage=resp_gen_stage,
    )
