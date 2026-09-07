
"""
app/modules/search/pipeline/response_generation.py

Pipeline stage: Response Generation (Step 13 / Final Stage).

Assembles the final structured SearchResponse from the information produced
by the previous pipeline stages.

Step 13 is an assembly/presentation stage. It must not perform new retrieval,
analysis, validation, or repository modifications.
"""

from __future__ import annotations

from app.modules.search.domain.search_domain import SearchContext
from app.modules.search.schemas.search_schema import EvidenceItem, SearchResponse


class ResponseGenerationStage:
    """Assemble the final structured search response."""

    _EARLY_EXITS = {
        "EARLY_EXIT_A",
        "EARLY_EXIT_B",
        "EARLY_EXIT_C",
        "EARLY_EXIT_D",
    }

    async def execute(self, context: SearchContext) -> None:
        """Build and store the final SearchResponse."""

        intent_str = context.intent.value if context.intent else "unknown"

        repo_info = {
            "id": context.repo_id,
            "owner": context.repo_owner,
            "name": context.repo_name,
            "collection": context.qdrant_collection,
        }

        target_info = {
            "file_path": (
                context.primary_chunk.file_path
                if context.primary_chunk
                else None
            ),
            "symbol": context.target_symbol,
            "primary_chunk_hash": (
                context.primary_chunk.chunk_hash
                if context.primary_chunk
                else None
            ),
        }

        validation_payload = {
            "validated": context.validated,
            "validation_status": (
                context.validation_status
                or ("passed" if context.validated else "pending")
            ),
            "validation_errors": list(context.validation_errors),
            "retries": context.validation_retries,
        }

        evidence_items = self._build_evidence(context)

        # ---------------------------------------------------------------
        # Early exits
        # ---------------------------------------------------------------
        if context.early_exit in self._EARLY_EXITS:
            context.final_response = self._build_early_exit_response(
                context=context,
                intent_str=intent_str,
                repo_info=repo_info,
                target_info=target_info,
                validation_payload=validation_payload,
                evidence_items=evidence_items,
            )
            return

        # ---------------------------------------------------------------
        # Normal flow
        # ---------------------------------------------------------------
        diff_or_change = None
        if context.action_analysis:
            diff_or_change = context.action_analysis.get("diff_or_change")

        analysis_payload = dict(context.analysis_result or {})

        # Preserve the actual Step 10 validation result.
        analysis_payload["validated"] = context.validated
        analysis_payload["validation_status"] = (
            context.validation_status
            or ("passed" if context.validated else "pending")
        )

        if context.validation_errors:
            analysis_payload["validation_errors"] = list(
                context.validation_errors
            )

        # Step 12 is the final triage/safety assessment.
        # Do not invent a new recommendation here.
        ai_suggestion = self._build_ai_suggestion(context)

        context.final_response = SearchResponse(
            intent=intent_str,
            repository=repo_info,
            target=target_info,
            code_context=context.code_snippets,
            ai_triage=context.triage_result,
            ai_suggestion=ai_suggestion,
            diff_or_change=diff_or_change,
            validation=validation_payload,
            analysis=analysis_payload,
            evidence=evidence_items,
            early_exit=None,
        )

    def _build_evidence(
        self,
        context: SearchContext,
    ) -> list[EvidenceItem]:
        """Convert retrieved chunks into response evidence."""

        evidence_items: list[EvidenceItem] = []

        for chunk in context.retrieved_chunks:
            snippet = chunk.content[:200]

            if len(chunk.content) > 200:
                snippet += "..."

            evidence_items.append(
                EvidenceItem(
                    file_path=chunk.file_path,
                    snippet=snippet,
                    score=round(chunk.score, 4),
                )
            )

        return evidence_items

    def _build_ai_suggestion(
        self,
        context: SearchContext,
    ):
        """
        Select the final suggestion without performing additional analysis.

        Step 12 is the preferred source because it combines the validated
        analysis with confidence and safety information.
        """

        if context.triage_result:
            suggestion = context.triage_result.get("ai_suggestion")

            if suggestion is not None:
                return suggestion

            recommendation = context.triage_result.get("recommendation")

            if recommendation is not None:
                return recommendation

        return context.analysis_result

    def _build_early_exit_response(
        self,
        context: SearchContext,
        intent_str: str,
        repo_info: dict,
        target_info: dict,
        validation_payload: dict,
        evidence_items: list[EvidenceItem],
    ) -> SearchResponse:
        """Build a safe response when the pipeline exits early."""

        early_exit_code = context.early_exit

        message = (
            context.early_exit_message
            or "Search could not be completed."
        )

        # Validation has not necessarily failed for A/B/C.
        # Those exits mean the pipeline stopped before completion.
        validation = dict(validation_payload)

        if early_exit_code != "EARLY_EXIT_D":
            validation["validated"] = False
            validation["validation_status"] = "skipped"

        analysis_payload = dict(context.analysis_result or {})

        analysis_payload.update(
            {
                "validated": validation["validated"],
                "validation_status": validation["validation_status"],
            }
        )

        if context.validation_errors:
            analysis_payload["validation_errors"] = list(
                context.validation_errors
            )

        analysis_payload["early_exit"] = early_exit_code
        analysis_payload["message"] = message

        if early_exit_code == "EARLY_EXIT_D":
            analysis_payload["warning"] = (
                "Proposed changes failed validation against repository "
                "evidence and should not be applied automatically."
            )

        diff_or_change = None

        if context.action_analysis:
            diff_or_change = context.action_analysis.get(
                "diff_or_change"
            )

        return SearchResponse(
            intent=intent_str,
            repository=repo_info,
            target=target_info,
            code_context=context.code_snippets,
            ai_triage=context.triage_result,
            ai_suggestion=(
                context.triage_result
                if context.triage_result
                else context.analysis_result
            ),
            diff_or_change=diff_or_change,
            validation=validation,
            analysis=analysis_payload,
            evidence=evidence_items,
            early_exit={
                "code": early_exit_code,
                "message": message,
            },
        )

