
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
    RetrievedChunk,
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
from app.modules.search.pipeline.deep_search_decision import (
    decide_deep_search_escalation,
)

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

    @staticmethod
    def _should_escalate_to_deep_search(context: SearchContext) -> bool:
        """
        Post-retrieval escalation check for FIX_BUG.

        After normal retrieval and analysis, determine whether the
        evidence is insufficient or signals a cross-component dependency
        that Deep Search should investigate.

        This only escalates when:
        - Intent is FIX_BUG.
        - Deep Search was NOT already selected initially.
        - No early exit has already been triggered.
        - The escalation decision returns selected=True.
        """
        if context.intent != IntentType.FIX_BUG:
            return False

        if context.early_exit:
            return False

        # Already selected by initial decision -- no escalation needed.
        parameters = context.intent_parameters or {}
        if (
            isinstance(parameters, dict)
            and parameters.get("deep_search_requested") is True
        ):
            return False

        decision = decide_deep_search_escalation(
            query=context.query,
            retrieved_chunks=context.retrieved_chunks,
            analysis_result=context.analysis_result,
        )

        return decision.selected

    @staticmethod
    def _transfer_deep_search_chunks(context: SearchContext) -> None:
        """
        Transfer retrieved chunks from deep_search_result to context.retrieved_chunks.
        """
        result = getattr(context, "deep_search_result", None)
        if not isinstance(result, dict):
            return

        raw_chunks = result.get("retrieved_chunks") or []
        existing_chunks = list(context.retrieved_chunks or [])
        existing_hashes = {
            getattr(c, "chunk_hash", "")
            or f"{getattr(c, 'file_path', '')}:{getattr(c, 'content', '')[:50]}"
            for c in existing_chunks
        }
        new_chunks = list(existing_chunks)

        for c in raw_chunks:
            if isinstance(c, RetrievedChunk):
                h = c.chunk_hash or f"{c.file_path}:{c.content[:50]}"
                if h not in existing_hashes:
                    existing_hashes.add(h)
                    new_chunks.append(c)
            elif isinstance(c, dict):
                fp = str(
                    c.get("file_path") or c.get("path") or ""
                ).replace("\\", "/")
                content = str(
                    c.get("content") or c.get("code") or c.get("text") or ""
                )
                score = float(c.get("score") or 0.0)
                meta = dict(c.get("metadata") or {})
                if "file_path" not in meta and fp:
                    meta["file_path"] = fp
                line_start = (
                    c.get("line_start")
                    or c.get("start_line")
                    or meta.get("start_line")
                )
                line_end = (
                    c.get("line_end")
                    or c.get("end_line")
                    or meta.get("end_line")
                )
                if line_start is not None and "start_line" not in meta:
                    meta["start_line"] = line_start
                if line_end is not None and "end_line" not in meta:
                    meta["end_line"] = line_end
                h = str(c.get("chunk_hash") or f"{fp}:{line_start}-{line_end}")
                if h not in existing_hashes:
                    existing_hashes.add(h)
                    new_chunks.append(
                        RetrievedChunk(
                            chunk_hash=h,
                            file_path=fp,
                            content=content,
                            score=score,
                            metadata=meta,
                        )
                    )

        if not new_chunks and result.get("evidence"):
            for ev in result["evidence"]:
                if isinstance(ev, dict) and ev.get("quote"):
                    fp = str(ev.get("path") or "").replace("\\", "/")
                    content = str(ev.get("quote") or "")
                    line_start = ev.get("line_start")
                    line_end = ev.get("line_end")
                    meta = {
                        "file_path": fp,
                        "start_line": line_start,
                        "end_line": line_end,
                        "evidence_claim": ev.get("claim"),
                    }
                    h = f"{fp}:{line_start}-{line_end}:{content[:30]}"
                    if h not in existing_hashes:
                        existing_hashes.add(h)
                        new_chunks.append(
                            RetrievedChunk(
                                chunk_hash=h,
                                file_path=fp,
                                content=content,
                                score=1.0,
                                metadata=meta,
                            )
                        )

        context.retrieved_chunks = new_chunks

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
                "deep_search_selection_check",
                intent=(
                    context.intent.value
                    if context.intent is not None
                    else None
                ),
                deep_search_requested=(
                    (context.intent_parameters or {}).get(
                        "deep_search_requested", False
                    )
                    if isinstance(context.intent_parameters, dict)
                    else False
                ),
                deep_search_selected=deep_search_selected,
                deep_search_reason=(
                    (context.intent_parameters or {}).get("deep_search_reason")
                    if isinstance(context.intent_parameters, dict)
                    else None
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
            # Only for FIX_BUG requiring Deep Search: execute Deep Search to
            # retrieve cross-file context, transfer retrieved chunks into
            # context.retrieved_chunks, and continue to context building
            # and subsequent pipeline stages.
            if deep_search_selected:
                logger.info(
                    "deep_search_stage_selected_and_executing",
                    repo_name=context.repo_name,
                    intent=context.intent.value if context.intent else None,
                    collection=context.qdrant_collection,
                    deep_search_requested=True,
                )

                await self._execute_stage(
                    self.deep_search_stage,
                    context,
                    5,
                )

                # Check the actual result before interpreting early_exit.
                result = context.deep_search_result

                if not isinstance(result, dict):
                    context.early_exit = "DEEP_SEARCH_UNAVAILABLE"
                    context.early_exit_message = (
                        "Deep Search did not produce a usable investigation "
                        "result. No root cause or fix will be assumed."
                    )

                    return await self._generate_response(context)

                result_status = result.get("status")

                # Transfer retrieved chunks from deep search into context.retrieved_chunks
                self._transfer_deep_search_chunks(context)

                if not context.retrieved_chunks:
                    logger.warning(
                        f"[DeepSearch] Deep Search ended with status '{result_status}' for repo '{context.repo_name}' "
                        f"(reason: {result.get('reason')}). No code chunks retrieved.",
                        repo_name=context.repo_name,
                        status=result_status,
                        reason=result.get("reason"),
                    )
                    context.early_exit = "DEEP_SEARCH_UNAVAILABLE"
                    context.early_exit_message = (
                        result.get("reason")
                        or "Deep Search did not retrieve code chunks. No root cause or fix will be assumed."
                    )
                    return await self._generate_response(context)

                # Context was retrieved by Deep Search.
                # Clear early_exit so context building and subsequent stages execute.
                context.early_exit = None

                stages_after_deep_search = [
                    self.code_ident_stage,
                    self.ctx_build_stage,
                    self.code_analysis_stage,
                    self.ev_val_stage,
                    self.action_analysis_stage,
                    self.suggestion_patch_stage,
                    self.suggestion_validation_stage,
                    self.final_triage_stage,
                ]

                stage_number = 6
                for stage in stages_after_deep_search:
                    should_continue = await self._execute_stage(
                        stage,
                        context,
                        stage_number,
                    )
                    stage_number += 1

                    if not should_continue:
                        break

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

                # After CodeAnalysisStage, check whether the evidence
                # warrants escalating to Deep Search.  The check is
                # bounded and does not run for any other intent.
                if isinstance(stage, CodeAnalysisStage):
                    if self._should_escalate_to_deep_search(context):
                        escalation_reason = decide_deep_search_escalation(
                            query=context.query,
                            retrieved_chunks=context.retrieved_chunks,
                            analysis_result=context.analysis_result,
                        ).reason

                        logger.info(
                            "deep_search_escalation_triggered",
                            repo_name=context.repo_name,
                            reason=escalation_reason,
                        )

                        # Mark the context so DeepSearchStage will execute.
                        parameters = dict(context.intent_parameters or {})
                        parameters["deep_search_requested"] = True
                        parameters["deep_search_reason"] = escalation_reason
                        parameters["deep_search_escalated"] = True
                        context.intent_parameters = parameters

                        # Reset early_exit so DeepSearchStage is not skipped.
                        context.early_exit = None

                        await self._execute_stage(
                            self.deep_search_stage,
                            context,
                            stage_number,
                        )
                        stage_number += 1

                        self._transfer_deep_search_chunks(context)

                        if context.retrieved_chunks:
                            context.early_exit = None

                            escalation_stages = [
                                self.ctx_build_stage,
                                self.code_analysis_stage,
                                self.ev_val_stage,
                                self.action_analysis_stage,
                                self.suggestion_patch_stage,
                                self.suggestion_validation_stage,
                                self.final_triage_stage,
                            ]

                            for esc_stage in escalation_stages:
                                should_continue = await self._execute_stage(
                                    esc_stage,
                                    context,
                                    stage_number,
                                )
                                stage_number += 1

                                if not should_continue:
                                    break

                            return await self._generate_response(context)

                        result = context.deep_search_result
                        status_str = result.get("status") if isinstance(result, dict) else "unknown"
                        reason_str = result.get("reason") if isinstance(result, dict) else None
                        logger.warning(
                            f"[DeepSearch] Escalated deep search ended with status '{status_str}' for repo '{context.repo_name}' "
                            f"(reason: {reason_str}). Resuming normal pipeline.",
                            repo_name=context.repo_name,
                            status=status_str,
                        )
                        context.early_exit = None
                        context.early_exit_message = None

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
