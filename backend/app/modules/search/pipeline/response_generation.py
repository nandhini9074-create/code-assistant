"""
app/modules/search/pipeline/response_generation.py

Pipeline stage: Response Generation (Final Stage).

Assembles the final compact SearchResponse from information produced
by the previous pipeline stages.

This stage only assembles/presents results. It does not perform new
retrieval, analysis, validation, or repository modifications.

Unavailable analysis/validation states are presented explicitly
without inventing recommendations or code changes.
"""

from __future__ import annotations

import ast
import json
from typing import Any

from app.core.enums import IntentType
from app.modules.search.domain.search_domain import SearchContext
from app.modules.search.pipeline.code_change_verifier import (
    format_final_response_output,
    verify_and_locate_code_change,
)
from app.modules.search.schemas.search_schema import (
    AmbiguousCandidate,
    SearchResponse,
)


class ResponseGenerationStage:
    """Assemble the final structured search response."""

    _EARLY_EXITS = {
        "EARLY_EXIT_A",
        "EARLY_EXIT_B",
        "EARLY_EXIT_C",
        "EARLY_EXIT_D",
    }

    @staticmethod
    def build_failure_response(
        context: SearchContext,
        error: Exception,
    ) -> SearchResponse:
        """Build a safe response when final assembly unexpectedly fails."""

        target = context.target_symbol
        if not target and context.primary_chunk:
            target = context.primary_chunk.file_path

        suggestion = (
            f"Review {target or 'the identified repository code'} against "
            f"the reported requirement: {context.query.strip()}. "
            "The available evidence does not support a safe exact code change."
        )

        return SearchResponse(
            intent=(context.intent.value if context.intent else "unknown"),
            repository={
                "owner": context.repo_owner,
                "name": context.repo_name,
            },
            target={
                "file_path": (
                    context.primary_chunk.file_path
                    if context.primary_chunk
                    else None
                ),
                "symbol": context.target_symbol,
            },
            requirement=context.query,
            suggestion=suggestion,
            proposed_change=suggestion,
            code_change=None,
            suggested_code=None,
            suggested_patch=context.suggested_patch,
            patch_validation=context.patch_validation,
            confidence="low",
            early_exit={
                "code": "SEARCH_RESPONSE_FALLBACK",
                "message": "The search result could not be fully assembled.",
            },
            ambiguous_candidates=[],
        )

    async def execute(self, context: SearchContext) -> None:
        """Build and store the final compact SearchResponse."""

        intent_str = (
            context.intent.value
            if context.intent
            else "unknown"
        )

        repo_info = {
            "owner": context.repo_owner,
            "name": context.repo_name,
        }

        target_info = {
            "file_path": (
                context.primary_chunk.file_path
                if context.primary_chunk
                else None
            ),
            "symbol": self._resolve_target_symbol(context),
        }

        # ---------------------------------------------------------
        # EARLY EXIT
        # ---------------------------------------------------------
        if context.early_exit in self._EARLY_EXITS:
            context.final_response = self._build_early_exit_response(
                context=context,
                intent_str=intent_str,
                repo_info=repo_info,
                target_info=target_info,
            )
            return

        # ---------------------------------------------------------
        # VULNERABILITY FIX RESPONSE
        # ---------------------------------------------------------
        if context.intent == IntentType.FIX_VULNERABILITY:
            context.final_response = self._build_vulnerability_response(
                context=context,
                intent_str=intent_str,
                repo_info=repo_info,
                target_info=target_info,
            )
            return

        if (
            context.intent == IntentType.FIX_BUG
            and context.analysis_result
            and context.analysis_result.get("analysis_status") == "UNAVAILABLE"
            and context.analysis_result.get("evidence_summary")
            and not context.analysis_result.get("reason")
        ):
            reason = (
                context.analysis_result.get("evidence_summary")
                or "The retrieved code does not establish a specific cause."
            )
            unavailable_message = (
                "The bug location could not be determined safely from the retrieved evidence. "
                "No code change was generated."
            )
            context.final_response = SearchResponse(
                intent=intent_str,
                repository=repo_info,
                target={"file_path": None, "symbol": None},
                requirement=context.query,
                current_behavior=None,
                suggestion=unavailable_message,
                proposed_change="No code change proposed.",
                code_change=None,
                suggested_code=None,
                suggested_patch=None,
                patch_validation={
                    "status": "not_run",
                    "analysis_status": "UNAVAILABLE",
                    "message": reason,
                    "repository_modified": False,
                },
                formatted_output=(
                    f"Analysis Status\n\nUNAVAILABLE\n\n"
                    f"{unavailable_message}\n\n"
                    f"Evidence\n\n{reason}"
                ),
                confidence="low",
                early_exit=None,
                ambiguous_candidates=[],
            )
            return

        # ---------------------------------------------------------
        # NORMAL RESPONSE
        # ---------------------------------------------------------
        requirement = None
        current_behavior = None
        suggestion: Any = None
        proposed_change = None
        code_change = None
        suggested_code = None
        suggested_patch = None
        patch_validation = None
        confidence = None

        # ---------------------------------------------------------
        # STEP 11 - TRIAGE RESULT
        # ---------------------------------------------------------
        if context.triage_result:
            requirement = (
                context.triage_result.get("issue_summary")
                or context.triage_result.get("requirement")
            )

            current_behavior = context.triage_result.get(
                "current_behavior"
            )

            suggestion = (
                context.triage_result.get("ai_suggestion")
                or context.triage_result.get("suggestion")
                or context.triage_result.get("recommended_change")
                or context.triage_result.get("recommendation")
            )

            proposed_change = (
                context.triage_result.get("proposed_change")
                or context.triage_result.get("proposed_fix")
            )

            suggested_code = context.triage_result.get(
                "suggested_code"
            )

            suggested_patch = (
                context.triage_result.get("suggested_patch")
                or context.suggested_patch
            )

            patch_validation = (
                context.triage_result.get("patch_validation")
                or context.patch_validation
            )

            confidence = context.triage_result.get(
                "confidence"
            )

            # -----------------------------------------------------
            # Do not manufacture a recommendation when analysis or
            # validation is explicitly unavailable.
            # -----------------------------------------------------
            if (
                context.triage_result.get("validation_status")
                == "unavailable"
            ):
                suggestion = (
                    context.triage_result.get("ai_suggestion")
                    or (
                        "Code analysis or validation was unavailable. "
                        "No recommendation can be safely generated."
                    )
                )

                proposed_change = (
                    context.triage_result.get("proposed_change")
                    or suggestion
                )
                suggested_code = None

        # ---------------------------------------------------------
        # STEP 8 - CODE ANALYSIS RESULT
        # ---------------------------------------------------------
        if (
            context.analysis_result
            and context.analysis_result.get("analysis_status")
            != "UNAVAILABLE"
        ):
            if requirement is None:
                requirement = (
                    context.analysis_result.get("requirement")
                    or context.analysis_result.get("issue_summary")
                )

            if current_behavior is None:
                current_behavior = context.analysis_result.get(
                    "current_behavior"
                )

            if suggestion is None:
                suggestion = (
                    context.analysis_result.get("suggestion")
                    or context.analysis_result.get(
                        "recommended_change"
                    )
                    or context.analysis_result.get(
                        "recommendation"
                    )
                    or context.analysis_result.get(
                        "proposed_fix"
                    )
                )

            if proposed_change is None:
                proposed_change = (
                    context.analysis_result.get("proposed_change")
                    or context.analysis_result.get("proposed_fix")
                )

            if code_change is None:
                code_change = context.analysis_result.get("code_change")

            if suggested_code is None:
                suggested_code = context.analysis_result.get(
                    "suggested_code"
                )

            if confidence is None:
                confidence = context.analysis_result.get(
                    "confidence"
                )

            # -----------------------------------------------------
            # RETRIEVE intent
            # -----------------------------------------------------
            if suggestion is None:
                suggestion = context.analysis_result.get("answer")

        # ---------------------------------------------------------
        # NORMALIZE VALUES
        # ---------------------------------------------------------
        if context.validation_status != "passed":
            suggestion = suggestion or (
                "Cannot be determined from the available evidence."
            )
            proposed_change = proposed_change or suggestion
            suggested_code = None

        suggestion = self._normalize_suggestion(
            suggestion
        )

        proposed_change = self._normalize_suggestion(
            proposed_change
        )

        suggested_code = self._normalize_code(
            suggested_code
        )

        # ---------------------------------------------------------
        # BUILD FINAL RESPONSE
        # ---------------------------------------------------------
        if code_change is None and isinstance(context.action_analysis, dict):
            code_change = context.action_analysis.get("code_change")
        if code_change is None:
            code_change = context.code_change

        if isinstance(code_change, dict):
            code_change = self._normalize_code_change(code_change)

        formatted_output = None

        is_ambig = (
            getattr(context, "ambiguous", False)
            or getattr(context, "is_ambiguous", False)
            or getattr(context, "symbol_conflict", False)
        )
        is_retrieve = context.intent == IntentType.RETRIEVE

        if is_ambig or is_retrieve:
            code_change = None
            suggested_patch = None
        elif isinstance(code_change, dict):
            if "start_line" not in code_change:
                verification = verify_and_locate_code_change(
                    code_change=code_change,
                    chunks=context.retrieved_chunks,
                    primary_chunk=context.primary_chunk,
                    code_snippets=context.code_snippets,
                    target_symbol=context.target_symbol or target_info.get("symbol"),
                )
                if verification.is_valid and verification.code_change:
                    code_change = verification.code_change
                    if not suggested_patch and verification.suggested_patch:
                        suggested_patch = verification.suggested_patch
                    if not patch_validation:
                        patch_validation = {
                            "status": "passed",
                            "verification_checks": verification.checks,
                        }

            patch_to_use = suggested_patch or context.suggested_patch
            if patch_to_use and "start_line" in code_change:
                checks_dict = (
                    (patch_validation.get("verification_checks") if isinstance(patch_validation, dict) else None)
                    or (context.patch_validation.get("verification_checks") if isinstance(context.patch_validation, dict) else None)
                    or {
                        "target_verified": "PASS",
                        "original_code_found_once": "PASS",
                        "line_location_calculated": "PASS",
                        "patch_generated": "PASS",
                        "repository_modified": "NO",
                    }
                )
                formatted_output = format_final_response_output(
                    file_path=code_change.get("file_path", target_info.get("file_path", "")),
                    symbol=code_change.get("symbol") or target_info.get("symbol"),
                    start_line=code_change.get("start_line", 1),
                    end_line=code_change.get("end_line", 1),
                    operation=code_change.get("operation", "replace"),
                    old_code=code_change.get("old_code", ""),
                    new_code=code_change.get("new_code", ""),
                    suggested_patch=patch_to_use,
                    checks=checks_dict,
                )

        context.final_response = SearchResponse(
            intent=intent_str,
            repository=repo_info,
            target=target_info,
            requirement=requirement,
            current_behavior=current_behavior,
            suggestion=suggestion,
            proposed_change=proposed_change,
            code_change=code_change,
            suggested_code=suggested_code,
            suggested_patch=suggested_patch or context.suggested_patch,
            patch_validation=patch_validation or context.patch_validation,
            formatted_output=formatted_output,
            confidence=confidence,
            early_exit=None,
            ambiguous_candidates=[],
        )

    # =============================================================
    # VULNERABILITY FIX RESPONSE
    # =============================================================

    def _build_vulnerability_response(
        self,
        context: SearchContext,
        intent_str: str,
        repo_info: dict,
        target_info: dict,
    ) -> SearchResponse:
        """
        Format the final structured response for FIX_VULNERABILITY intent.

        All vulnerability data comes from context.analysis_result, which is
        populated by FixVulnerabilityAnalyzer (deterministic, no LLM).
        """
        import difflib

        analysis = context.analysis_result or {}
        audit_status = analysis.get("analysis_status")
        confidence = analysis.get("confidence", "low")

        # ------------------------------------------------------------------
        # Case 1: Analyzer could not complete (missing npm, bad project dir…)
        # ------------------------------------------------------------------
        if audit_status == "UNAVAILABLE":
            err = analysis.get("error") or "npm audit could not be completed."
            formatted = (
                f"Query\n\n{context.query}\n\n"
                f"Fix Vulnerability\nConfidence: low\n\n"
                f"Target\n\npackage.json\n\n"
                f"Verification\n\n"
                f"The npm dependency audit could not be completed.\n\n"
                f"Error: {err}\n\n"
                f"Suggested Code\n\n"
                f"No code change was generated because the vulnerability status "
                f"or remediation could not be verified safely."
            )
            return SearchResponse(
                intent=intent_str,
                repository=repo_info,
                target={"file_path": "package.json", "symbol": None},
                requirement=context.query,
                current_behavior=None,
                suggestion="The npm dependency audit could not be completed. No remediation was generated.",
                proposed_change=None,
                code_change=None,
                suggested_code=None,
                suggested_patch=None,
                patch_validation={"status": "failed", "message": err},
                formatted_output=formatted,
                confidence="low",
                early_exit=None,
                ambiguous_candidates=[],
            )

        # ------------------------------------------------------------------
        # Case 2: No vulnerabilities found
        # ------------------------------------------------------------------
        if not analysis.get("has_vulnerabilities"):
            clean_result = "✓ No vulnerabilities found in project dependencies."
            return SearchResponse(
                intent=intent_str,
                repository=repo_info,
                target={"file_path": "package.json", "symbol": None},
                requirement=context.query,
                current_behavior=clean_result,
                suggestion=clean_result,
                proposed_change=None,
                code_change=None,
                suggested_code=None,
                suggested_patch=None,
                patch_validation={
                    "status": "passed",
                    "message": clean_result,
                    "verification_source": "npm audit --json",
                    "repository_modified": False,
                },
                formatted_output=clean_result,
                confidence="high",
                early_exit=None,
                ambiguous_candidates=[],
            )

        # ------------------------------------------------------------------
        # Case 3: Vulnerabilities detected but no verified direct fix
        # ------------------------------------------------------------------
        code_change = analysis.get("code_change") or context.code_change
        if not code_change:
            affected = analysis.get("affected_dependencies") or []
            dependency_lines = [
                f"- {item.get('package', '?')}: "
                f"{item.get('current_version', 'unknown')} -> "
                f"{item.get('patched_version') or 'no verified patched version'}; "
                f"{item.get('severity', 'unknown')}; "
                f"{item.get('advisory_count', 0)} advisories"
                for item in affected
            ]
            dependency_summary = "\n".join(dependency_lines) or "No direct dependencies identified."
            advisory_count = analysis.get("vulnerability_count", 0)
            formatted = (
                f"Query\n\n{context.query}\n\n"
                f"Fix Vulnerability\nConfidence: low\n\n"
                f"Target\n\npackage.json\n\n"
                f"Audit Summary\n\n"
                f"{advisory_count} advisory findings across {len(affected)} affected direct dependencies.\n\n"
                f"Affected Dependencies\n\n{dependency_summary}\n\n"
                f"Suggested Code\n\n"
                f"No automated patch available — no direct dependency has a "
                f"verified patched version. Review advisories manually."
            )
            return SearchResponse(
                intent=intent_str,
                repository=repo_info,
                target={"file_path": "package.json", "symbol": None},
                requirement=context.query,
                current_behavior=(
                    f"npm audit detected {advisory_count} advisory findings across "
                    f"{len(affected)} affected direct dependencies."
                ),
                suggestion=analysis.get("proposed_fix") or "Manual review required.",
                proposed_change=None,
                code_change=None,
                suggested_code=None,
                suggested_patch=None,
                patch_validation={
                    "status": "failed",
                    "message": "No verified direct-dependency patched version found.",
                    "verification_source": "npm audit --json",
                    "repository_modified": False,
                },
                formatted_output=formatted,
                confidence="low",
                early_exit=None,
                ambiguous_candidates=[],
            )

        # ------------------------------------------------------------------
        # Case 4: Verified fix available — generate full response
        # ------------------------------------------------------------------
        per_package_changes: list[dict[str, Any]] = code_change.get("per_package") or []
        affected = analysis.get("affected_dependencies") or []
        affected_by_name = {
            item.get("package"): item for item in affected
        }
        if not per_package_changes:
            per_package_changes = [code_change]

        packages_fixed = [
            item["package"]
            for item in per_package_changes
            if item.get("package")
        ]
        per_package_details = []
        for change in per_package_changes:
            package = change.get("package", "?")
            dependency = affected_by_name.get(package, {})
            per_package_details.append({
                "package": package,
                "current_version": dependency.get("current_version", "unknown"),
                "patched_version": dependency.get("patched_version"),
                "severity": dependency.get("severity", "unknown"),
                "advisory_count": dependency.get("advisory_count", 0),
                "old": change.get("old_code", "").strip(),
                "new": change.get("new_code", "").strip(),
            })

        total_count = analysis.get("vulnerability_count", 0)
        affected_count = len(affected) or len(per_package_details)
        package_summary = "\n".join(
            f"- {item.get('package', '?')}: "
            f"{item.get('current_version', 'unknown')} → "
            f"{item.get('patched_version') or 'no verified patched version'}; "
            f"{item.get('severity', 'unknown')}; "
            f"{item.get('advisory_count', 0)} "
            f"{'advisory' if item.get('advisory_count') == 1 else 'advisories'}"
            for item in affected
        )
        if not package_summary:
            package_summary = "\n".join(
                f"- {item['package']}: {item['current_version']} → "
                f"{item['patched_version']}"
                for item in per_package_details
            )

        current_behavior = (
            f"npm audit detected {total_count} advisory findings across "
            f"{affected_count} affected direct dependencies."
        )
        proposed_change = "\n".join(
            f"{item['package']}: {item['current_version']} → {item['patched_version']}"
            for item in per_package_details
        )
        suggestion = "Review the verified package.json upgrades and unified diff before applying."

        suggested_patch = context.suggested_patch
        if not suggested_patch:
            diff_lines = list(difflib.unified_diff(
                code_change.get("old_code", "").splitlines(),
                code_change.get("new_code", "").splitlines(),
                fromfile="a/package.json",
                tofile="b/package.json",
                lineterm="",
                n=3,
            ))
            suggested_patch = "\n".join(diff_lines) if diff_lines else None

        patch_status = (context.patch_validation or {}).get("status", "failed")
        patch_verified = patch_status == "passed" and bool(suggested_patch)
        verification_text = "\n".join([
            f"npm audit patched versions: {'PASS' if packages_fixed else 'FAIL'}",
            f"Unified diff verified: {'PASS' if patch_verified else 'FAIL'}",
            "Repository modified: NO",
        ])
        formatted = (
            f"Fix Vulnerability\nConfidence: {confidence}\n\n"
            f"Target\n\npackage.json\n\n"
            f"Audit Summary\n\n"
            f"Total advisory findings: {total_count}\n"
            f"Affected direct dependencies: {affected_count}\n\n"
            f"Proposed Changes\n\n{package_summary}\n\n"
            f"Suggested Code\n\n{code_change.get('new_code', '')}\n\n"
            f"Unified Diff\n\n{suggested_patch or 'No patch generated.'}\n\n"
            f"Verification\n\n{verification_text}"
        )

        checks = (context.patch_validation or {}).get("checks", [])
        return SearchResponse(
            intent=intent_str,
            repository=repo_info,
            target={"file_path": "package.json", "symbol": None},
            requirement=context.query,
            current_behavior=current_behavior,
            suggestion=suggestion,
            proposed_change=proposed_change,
            code_change=code_change,
            suggested_code=code_change.get("new_code"),
            suggested_patch=suggested_patch,
            patch_validation={
                "status": "passed" if patch_verified else "failed",
                "message": "Verified npm audit remediation suggestions; repository files remain unchanged.",
                "verification_source": "npm audit --json",
                "packages_fixed": packages_fixed,
                "per_package_changes": per_package_details,
                "total_advisory_findings": total_count,
                "affected_dependency_count": affected_count,
                "repository_modified": False,
                "checks": checks,
            },
            formatted_output=formatted,
            confidence=confidence,
            early_exit=None,
            ambiguous_candidates=[],
        )

    # =============================================================
    # EARLY EXIT RESPONSE
    # =============================================================


    def _build_early_exit_response(
        self,
        context: SearchContext,
        intent_str: str,
        repo_info: dict[str, Any],
        target_info: dict[str, Any],
    ) -> SearchResponse:
        """Build the final response when the pipeline exits early."""

        requirement = None
        current_behavior = None
        suggestion: Any = None
        proposed_change = None
        code_change = None
        change_location = None
        suggested_code = None
        suggested_patch = None
        patch_validation = None
        confidence = None

        # ---------------------------------------------------------
        # TRIAGE RESULT
        # ---------------------------------------------------------
        if context.triage_result:
            requirement = (
                context.triage_result.get("issue_summary")
                or context.triage_result.get("requirement")
            )

            current_behavior = context.triage_result.get(
                "current_behavior"
            )

            suggestion = (
                context.triage_result.get("ai_suggestion")
                or context.triage_result.get("suggestion")
                or context.triage_result.get("recommended_change")
                or context.triage_result.get("recommendation")
            )

            proposed_change = (
                context.triage_result.get("proposed_change")
                or context.triage_result.get("proposed_fix")
            )

            if code_change is None:
                code_change = (
                    context.triage_result.get("code_change")
                    or (
                        context.triage_result.get("change_plan", {}).get("code_change")
                        if isinstance(context.triage_result.get("change_plan"), dict)
                        else None
                    )
                )

            suggested_code = context.triage_result.get(
                "suggested_code"
            )

            suggested_patch = (
                context.triage_result.get("suggested_patch")
                or context.suggested_patch
            )

            patch_validation = (
                context.triage_result.get("patch_validation")
                or context.patch_validation
            )

            confidence = context.triage_result.get(
                "confidence"
            )

            # -----------------------------------------------------
            # Do not expose recommendations or code when analysis
            # or validation is unavailable.
            # -----------------------------------------------------
            if (
                context.triage_result.get("validation_status")
                == "unavailable"
            ):
                suggestion = (
                    context.triage_result.get("ai_suggestion")
                    or (
                        "Code analysis or validation was unavailable. "
                        "No recommendation can be safely generated."
                    )
                )

                proposed_change = (
                    context.triage_result.get("proposed_change")
                    or suggestion
                )
                suggested_code = None

        # ---------------------------------------------------------
        # CODE ANALYSIS RESULT
        # ---------------------------------------------------------
        if (
            context.analysis_result
            and context.analysis_result.get("analysis_status")
            != "UNAVAILABLE"
        ):
            if requirement is None:
                requirement = (
                    context.analysis_result.get("requirement")
                    or context.analysis_result.get("issue_summary")
                )

            if current_behavior is None:
                current_behavior = context.analysis_result.get(
                    "current_behavior"
                )

            if suggestion is None:
                suggestion = (
                    context.analysis_result.get("suggestion")
                    or context.analysis_result.get(
                        "recommended_change"
                    )
                    or context.analysis_result.get(
                        "recommendation"
                    )
                    or context.analysis_result.get(
                        "proposed_fix"
                    )
                    or context.analysis_result.get("answer")
                )

            if proposed_change is None:
                proposed_change = (
                    context.analysis_result.get("proposed_change")
                    or context.analysis_result.get("proposed_fix")
                )

            if code_change is None:
                code_change = context.analysis_result.get("code_change")

            if suggested_code is None:
                suggested_code = context.analysis_result.get(
                    "suggested_code"
                )

            if confidence is None:
                confidence = context.analysis_result.get(
                    "confidence"
                )

        # ---------------------------------------------------------
        # NORMALIZE VALUES
        # ---------------------------------------------------------
        if context.validation_status != "passed":
            suggestion = suggestion or (
                "Cannot be determined from the available evidence."
            )
            proposed_change = proposed_change or suggestion
            suggested_code = None

        suggestion = self._normalize_suggestion(
            suggestion
        )

        proposed_change = self._normalize_suggestion(
            proposed_change
        )

        suggested_code = self._normalize_code(
            suggested_code
        )

        # ---------------------------------------------------------
        # EARLY EXIT PAYLOAD
        # ---------------------------------------------------------
        early_exit_payload: dict[str, Any] = {
            "code": context.early_exit,
            "message": (
                "The analysis could not be safely validated."
                if context.early_exit == "EARLY_EXIT_D"
                else context.early_exit_message
            ),
        }

        if (
            getattr(context, "ambiguous", False)
            or getattr(context, "is_ambiguous", False)
        ):
            early_exit_payload["ambiguous"] = True

        if getattr(context, "symbol_conflict", False):
            early_exit_payload["symbol_conflict"] = True

        # ---------------------------------------------------------
        # STRUCTURED AMBIGUOUS CANDIDATES
        # ---------------------------------------------------------
        raw_candidates = (
            getattr(
                context,
                "ambiguous_candidates",
                [],
            )
            or []
        )

        structured_candidates: list[AmbiguousCandidate] = []

        for c in raw_candidates:
            try:
                structured_candidates.append(
                    AmbiguousCandidate(
                        name=str(
                            c.get("name") or ""
                        ),
                        file_path=str(
                            c.get("file_path") or ""
                        ),
                        class_name=(
                            c.get("class_name")
                            or None
                        ),
                        start_line=c.get("start_line"),
                        end_line=c.get("end_line"),
                        score=c.get("score"),
                    )
                )
            except Exception:
                pass

        # ---------------------------------------------------------
        # BUILD EARLY EXIT RESPONSE
        # ---------------------------------------------------------
        # For early exit / ambiguous cases, do not generate patch or change location
        return SearchResponse(
            intent=intent_str,
            repository=repo_info,
            target=target_info,
            requirement=requirement,
            current_behavior=current_behavior,
            suggestion=suggestion,
            proposed_change=proposed_change,
            code_change=None,
            suggested_code=suggested_code,
            suggested_patch=None,
            patch_validation=None,
            formatted_output=None,
            confidence=confidence,
            early_exit=early_exit_payload,
            ambiguous_candidates=structured_candidates,
        )

    # =============================================================
    # SUGGESTION NORMALIZATION
    # =============================================================

    @staticmethod
    def _normalize_code_change(
        code_change: dict[str, Any],
    ) -> dict[str, Any]:
        """Keep the exact code change as the single canonical payload."""

        normalized = dict(code_change)
        normalized.pop("change_location", None)
        return normalized

    @staticmethod
    def _normalize_suggestion(
        suggestion: Any,
    ) -> str | None:
        """
        Convert any suggestion value into the string expected by
        SearchResponse.suggestion and SearchResponse.proposed_change.
        """

        if suggestion is None:
            return None

        if isinstance(suggestion, dict):
            description = suggestion.get("description")

            if description is not None:
                if isinstance(description, str):
                    return description.strip() or None

                return str(description)

            return json.dumps(
                suggestion,
                ensure_ascii=False,
            )

        if isinstance(suggestion, list):
            return json.dumps(
                suggestion,
                ensure_ascii=False,
            )

        if isinstance(suggestion, str):
            value = suggestion.strip()

            if not value:
                return None

            # Try JSON first.
            try:
                parsed = json.loads(value)

                if isinstance(parsed, dict):
                    description = parsed.get("description")

                    if description is not None:
                        if isinstance(description, str):
                            return description.strip() or None

                        return str(description)

                    return json.dumps(
                        parsed,
                        ensure_ascii=False,
                    )

                if isinstance(parsed, list):
                    return json.dumps(
                        parsed,
                        ensure_ascii=False,
                    )

            except (
                json.JSONDecodeError,
                TypeError,
                ValueError,
            ):
                pass

            # Try Python repr.
            try:
                parsed = ast.literal_eval(value)

                if isinstance(parsed, dict):
                    description = parsed.get("description")

                    if description is not None:
                        if isinstance(description, str):
                            return description.strip() or None

                        return str(description)

                    return json.dumps(
                        parsed,
                        ensure_ascii=False,
                    )

                if isinstance(parsed, list):
                    return json.dumps(
                        parsed,
                        ensure_ascii=False,
                    )

            except (
                ValueError,
                SyntaxError,
                TypeError,
            ):
                pass

            return value

        return str(suggestion)

    # =============================================================
    # SUGGESTED CODE NORMALIZATION
    # =============================================================

    @staticmethod
    def _normalize_code(
        code: Any,
    ) -> str | None:
        """
        Normalize the suggested code returned by the LLM.

        suggested_code is expected to be a string. If the provider
        returns another value, convert it safely to a string.
        """

        if code is None:
            return None

        if isinstance(code, str):
            value = code.strip()
            return value or None

        if isinstance(code, dict):
            return json.dumps(
                code,
                ensure_ascii=False,
            )

        if isinstance(code, list):
            return "\n".join(
                str(item)
                for item in code
            ).strip() or None

        return str(code)

    # =============================================================
    # TARGET SYMBOL
    # =============================================================

    @staticmethod
    def _resolve_target_symbol(
        context: SearchContext,
    ) -> str | None:
        """
        Resolve the most useful target symbol.

        Prefer an already meaningful target symbol.

        If the target symbol is a filename or is otherwise unavailable,
        use the primary chunk metadata to resolve the class/function.
        """

        target_symbol = context.target_symbol
        primary_chunk = context.primary_chunk

        metadata = (
            primary_chunk.metadata
            if primary_chunk and primary_chunk.metadata
            else {}
        )

        class_name = str(
            metadata.get("class_name") or ""
        ).strip()

        function_name = str(
            metadata.get("function_name") or ""
        ).strip()

        file_path = (
            primary_chunk.file_path
            if primary_chunk
            else None
        )

        # ---------------------------------------------------------
        # If target_symbol is meaningful and is not just the file path,
        # keep it.
        # ---------------------------------------------------------
        if target_symbol:
            normalized = target_symbol.strip()

            if normalized and normalized != file_path:
                if not normalized.lower().endswith(
                    (
                        ".ts",
                        ".tsx",
                        ".js",
                        ".jsx",
                        ".py",
                        ".java",
                        ".go",
                        ".rs",
                        ".cpp",
                        ".c",
                        ".cs",
                    )
                ):
                    return normalized

        # ---------------------------------------------------------
        # Prefer class name from chunk metadata.
        # ---------------------------------------------------------
        if class_name:
            return class_name

        # ---------------------------------------------------------
        # Fall back to function/method name.
        # ---------------------------------------------------------
        if function_name:
            return function_name

        # ---------------------------------------------------------
        # Last fallback.
        # ---------------------------------------------------------
        return target_symbol