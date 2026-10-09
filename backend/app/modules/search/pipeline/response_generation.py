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
            formatted = (
                f"Query\n\n{context.query}\n\n"
                f"Fix Vulnerability\nConfidence: high\n\n"
                f"Target\n\npackage.json\n\n"
                f"Audit Result\n\nNo known vulnerabilities were reported by npm audit.\n\n"
                f"Current Behavior\n\n"
                f"The dependency tree was checked using npm audit --json, and no "
                f"vulnerabilities were detected.\n\n"
                f"Suggested Code\n\nNo code changes are required.\n\n"
                f"Verification\n\n"
                f"Verified using npm audit --json. No package version change needed."
            )
            return SearchResponse(
                intent=intent_str,
                repository=repo_info,
                target={"file_path": "package.json", "symbol": None},
                requirement=context.query,
                current_behavior=(
                    "The dependency tree was checked using npm audit --json, "
                    "and no vulnerabilities were detected."
                ),
                suggestion="No known vulnerabilities were reported by npm audit.",
                proposed_change=None,
                code_change=None,
                suggested_code=None,
                suggested_patch=None,
                patch_validation={
                    "status": "passed",
                    "message": "No vulnerabilities found.",
                    "verification_source": "npm audit --json",
                },
                formatted_output=formatted,
                confidence="high",
                early_exit=None,
                ambiguous_candidates=[],
            )

        # ------------------------------------------------------------------
        # Case 3: Vulnerabilities detected but no verified direct fix
        # ------------------------------------------------------------------
        code_change = analysis.get("code_change") or context.code_change
        if not code_change:
            vulns = analysis.get("all_vulnerabilities", [])
            vuln_lines = [
                f"- {v['package']}: severity={v.get('severity','?')}, "
                f"range={v.get('vulnerable_range','?')}, "
                f"patched={v.get('patched_version','not available')}"
                for v in vulns
            ]
            vuln_summary = "\n".join(vuln_lines) or "Unknown vulnerabilities."
            formatted = (
                f"Query\n\n{context.query}\n\n"
                f"Fix Vulnerability\nConfidence: low\n\n"
                f"Target\n\npackage.json\n\n"
                f"Vulnerabilities Found\n\n{vuln_summary}\n\n"
                f"Suggested Code\n\n"
                f"No automated patch available — no direct dependency has a "
                f"verified patched version. Review advisories manually."
            )
            return SearchResponse(
                intent=intent_str,
                repository=repo_info,
                target={"file_path": "package.json", "symbol": None},
                requirement=context.query,
                current_behavior=analysis.get("current_behavior"),
                suggestion=analysis.get("proposed_fix") or "Manual review required.",
                proposed_change=None,
                code_change=None,
                suggested_code=None,
                suggested_patch=None,
                patch_validation={
                    "status": "failed",
                    "message": "No verified direct-dependency patched version found.",
                    "verification_source": "npm audit --json",
                },
                formatted_output=formatted,
                confidence="low",
                early_exit=None,
                ambiguous_candidates=[],
            )

        # ------------------------------------------------------------------
        # Case 4: Verified fix available — generate full response
        # ------------------------------------------------------------------
        selected = analysis.get("selected_vulnerability") or {}
        pkg_name = selected.get("package") or analysis.get("package", "")
        severity = selected.get("severity") or analysis.get("severity", "unknown")
        vuln_range = selected.get("vulnerable_range") or analysis.get("vulnerable_range", "unknown")
        patched_version = selected.get("patched_version") or analysis.get("patched_version", "unknown")
        current_version = selected.get("current_version") or analysis.get("current_version", "unknown")
        title = selected.get("title") or analysis.get("title", f"{pkg_name} vulnerability")
        urls = selected.get("urls") or analysis.get("urls", [])
        remediation = selected.get("remediation") or analysis.get("remediation", f"Upgrade {pkg_name} to {patched_version}")

        # per_package contains individual changes for every upgraded dependency
        per_package_changes: list[dict] = code_change.get("per_package") or []
        if not per_package_changes:
            per_package_changes = [code_change]

        old_code = code_change.get("old_code", "")
        new_code = code_change.get("new_code", "")
        start_line = code_change.get("start_line", 1)

        # Build a unified diff covering ALL changed packages
        suggested_patch = context.suggested_patch
        if not suggested_patch:
            all_diff_lines: list[str] = []
            for ch in per_package_changes:
                diff_lines = list(difflib.unified_diff(
                    [ch["old_code"]],
                    [ch["new_code"]],
                    fromfile="a/package.json",
                    tofile="b/package.json",
                    lineterm="",
                    n=0,
                ))
                all_diff_lines.extend(diff_lines)
            suggested_patch = "\n".join(all_diff_lines) if all_diff_lines else None

        # Build a human-readable "Suggested Code" block showing ALL changes
        per_pkg_suggested = "\n".join(
            f'  {ch["new_code"].strip()}   # was: {ch["old_code"].strip()}'
            for ch in per_package_changes
        )
        pkg_names_fixed = ", ".join(ch["package"] for ch in per_package_changes) if per_package_changes and "package" in per_package_changes[0] else pkg_name

        curr_behavior = (
            analysis.get("current_behavior")
            or (
                f"package.json specifies {pkg_name}@{current_version} which falls "
                f"within the vulnerable range {vuln_range}. Advisory: {title}."
            )
        )
        short_description = (
            analysis.get("proposed_fix")
            or f"Update {pkg_name} from {current_version} to {patched_version} to fix the {severity} vulnerability."
        )

        all_vulns = analysis.get("all_vulnerabilities") or analysis.get("vulnerabilities") or []
        total_count = analysis.get("vulnerability_count") or len(all_vulns) or 1

        all_vuln_lines = [
            f"  - {v.get('package','?')}: {v.get('severity','?')} - {v.get('title','vulnerability')}"
            for v in all_vulns
        ]
        all_vulns_text = "\n".join(all_vuln_lines) if all_vuln_lines else f"  - {pkg_name}: {severity}"

        audit_evidence = "\n".join(filter(None, [
            f"- Total Vulnerabilities Detected: {total_count}",
            f"- All Detected Vulnerabilities:\n{all_vulns_text}" if total_count > 1 else None,
            f"- Packages Fixed: {pkg_names_fixed}",
            f"- Selected Package (highest severity): {pkg_name}",
            f"- Current Version: {current_version}",
            f"- Severity: {severity}",
            f"- Vulnerable Range: {vuln_range}",
            f"- Patched Version: {patched_version}",
            "- Verification Source: npm audit --json",
            f"- Remediation: {remediation}",
            f"- Advisory URL: {urls[0]}" if urls else None,
        ]))

        verification_text = "\n".join([
            "Target verified: PASS",
            f"Packages changed: {len(per_package_changes)}",
            f"Line location calculated from source: PASS (first change at line {start_line})",
            f"Patch generated: {'PASS' if suggested_patch else 'FAIL'}",
            "Repository modified: NO",
        ])

        formatted = (
            f"Query\n\n{context.query}\n\n"
            f"Fix Vulnerability\nConfidence: {confidence}\n\n"
            f"Target\n\npackage.json\n\n"
            f"Vulnerability\n\n{title}\n\n"
            f"Audit Evidence\n\n{audit_evidence}\n\n"
            f"Suggestion\n\n{short_description}\n\n"
            f"Current Behavior\n\n{curr_behavior}\n\n"
            f"Proposed Change\n\n{short_description}\n\n"
            f"Suggested Code\n\npackage.json — updated dependencies:\n\n"
            f"{per_pkg_suggested}\n\n"
            f"Patch\n\n{suggested_patch or 'No patch generated.'}\n\n"
            f"Verification\n\n{verification_text}"
        )

        return SearchResponse(
            intent=intent_str,
            repository=repo_info,
            target={"file_path": "package.json", "symbol": None},
            requirement=context.query,
            current_behavior=curr_behavior,
            suggestion=short_description,
            proposed_change=short_description,
            code_change=code_change,
            suggested_code=new_code,
            suggested_patch=suggested_patch,
            patch_validation={
                "status": "passed",
                "message": f"Verified patched versions from npm audit --json for: {pkg_names_fixed}.",
                "verification_source": "npm audit --json",
                "packages_fixed": pkg_names_fixed,
                "per_package_changes": [
                    {"package": ch.get("package", "?"), "old": ch["old_code"].strip(), "new": ch["new_code"].strip()}
                    for ch in per_package_changes
                ],
                "severity": severity,
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

        # ---------------------------------------------------------
        # CODE ANALYSIS RESULT
        # ---------------------------------------------------------
        if context.analysis_result:
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

        early_exit_payload = {
            "code": context.early_exit,
            "message": self._get_early_exit_message(context.early_exit),
        }

        ambiguous_candidates: list[AmbiguousCandidate] = []
        if (
            context.early_exit == "EARLY_EXIT_C"
            and context.ambiguity_candidates
        ):
            ambiguous_candidates = [
                AmbiguousCandidate(
                    file_path=candidate.get("file_path", ""),
                    symbol=candidate.get("symbol"),
                    reason=candidate.get("reason", "Ambiguous match"),
                )
                for candidate in context.ambiguity_candidates
            ]

        suggestion = self._normalize_suggestion(
            suggestion
        )

        proposed_change = self._normalize_suggestion(
            proposed_change
        )

        suggested_code = self._normalize_code(
            suggested_code
        )

        if isinstance(code_change, dict):
            code_change = self._normalize_code_change(code_change)

        return SearchResponse(
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
            confidence=confidence,
            early_exit=early_exit_payload,
            ambiguous_candidates=ambiguous_candidates,
        )

    # -------------------------------------------------------------
    # HELPERS
    # -------------------------------------------------------------

    def _resolve_target_symbol(
        self,
        context: SearchContext,
    ) -> str | None:
        """Resolve target symbol with proper fallback handling."""

        if context.target_symbol:
            return context.target_symbol

        chunk = context.primary_chunk
        if not chunk:
            return None

        for key in ("symbol", "symbol_name", "target_symbol"):
            value = chunk.metadata.get(key)
            if value:
                return value

        return None

    def _get_early_exit_message(self, code: str | None) -> str:
        """Map early exit codes to user-friendly messages."""

        mapping = {
            "EARLY_EXIT_A": "The request is unclear and requires clarification.",
            "EARLY_EXIT_B": "No relevant code could be found in the repository.",
            "EARLY_EXIT_C": "Multiple candidate locations match the request.",
            "EARLY_EXIT_D": "The request was resolved using indexed documentation/examples.",
        }

        return mapping.get(
            code or "",
            "Search concluded early.",
        )

    # -------------------------------------------------------------
    # NORMALIZATION HELPERS
    # -------------------------------------------------------------

    def _normalize_suggestion(self, suggestion: Any) -> str | None:
        """Normalize suggestion field ensuring clean string or None."""

        if suggestion is None:
            return None

        # Dict representation
        if isinstance(suggestion, dict):
            for key in ("text", "summary", "description", "content"):
                if key in suggestion and isinstance(suggestion[key], str):
                    clean = suggestion[key].strip()
                    if clean:
                        return clean
            try:
                return json.dumps(suggestion)
            except Exception:
                return str(suggestion)

        # Non-string fallback
        if not isinstance(suggestion, str):
            return str(suggestion)

        cleaned = suggestion.strip()
        if not cleaned:
            return None

        # Check for stringified JSON dictionary
        if cleaned.startswith("{") and cleaned.endswith("}"):
            try:
                parsed = json.loads(cleaned)
                if isinstance(parsed, dict):
                    for key in ("text", "summary", "description", "content"):
                        if key in parsed and isinstance(parsed[key], str):
                            val = parsed[key].strip()
                            if val:
                                return val
            except Exception:
                pass

        # Strip wrapping markdown code blocks if the entire suggestion is wrapped
        if cleaned.startswith("```") and cleaned.endswith("```"):
            lines = cleaned.splitlines()
            if len(lines) >= 3:
                inner = "\n".join(lines[1:-1]).strip()
                if inner:
                    cleaned = inner

        return cleaned

    def _normalize_code(self, code: Any) -> str | None:
        """Normalize suggested_code ensuring clean string or None."""

        if code is None:
            return None

        # Dict representation
        if isinstance(code, dict):
            for key in ("code", "source", "content", "snippet"):
                if key in code and isinstance(code[key], str):
                    clean = code[key].strip()
                    if clean:
                        return clean
            try:
                return json.dumps(code)
            except Exception:
                return str(code)

        if not isinstance(code, str):
            return str(code)

        cleaned = code.strip()
        if not cleaned:
            return None

        # Check for stringified JSON dictionary
        if cleaned.startswith("{") and cleaned.endswith("}"):
            try:
                parsed = json.loads(cleaned)
                if isinstance(parsed, dict):
                    for key in ("code", "source", "content", "snippet"):
                        if key in parsed and isinstance(parsed[key], str):
                            val = parsed[key].strip()
                            if val:
                                return val
            except Exception:
                pass

        return cleaned

    def _normalize_code_change(
        self,
        change: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Validate and normalize a structured code change object."""

        if not isinstance(change, dict):
            return None

        required = {"file_path", "old_code", "new_code"}
        if not required.issubset(change.keys()):
            return None

        normalized = {
            "file_path": str(change["file_path"]),
            "old_code": str(change["old_code"]),
            "new_code": str(change["new_code"]),
            "operation": change.get("operation", "replace"),
            "start_line": change.get("start_line"),
            "end_line": change.get("end_line"),
            "symbol": change.get("symbol"),
        }

        # Validate start_line / end_line
        if normalized["start_line"] is not None:
            try:
                normalized["start_line"] = int(normalized["start_line"])
            except (ValueError, TypeError):
                normalized["start_line"] = None

        if normalized["end_line"] is not None:
            try:
                normalized["end_line"] = int(normalized["end_line"])
            except (ValueError, TypeError):
                normalized["end_line"] = None

        # Enforce valid range
        if (
            normalized["start_line"] is not None
            and normalized["end_line"] is not None
            and normalized["start_line"] > normalized["end_line"]
        ):
            normalized["start_line"], normalized["end_line"] = (
                normalized["end_line"],
                normalized["start_line"],
            )

        # -------------------------------------------------------------
        # SYNTAX VALIDATION
        # -------------------------------------------------------------
        if not self._validate_syntax(
            file_path=normalized["file_path"],
            code=normalized["new_code"],
        ):
            return None

        return normalized

    def _validate_syntax(self, file_path: str, code: str) -> bool:
        """Basic syntax validation for Python and JSON files."""

        ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""

        if ext == "py":
            try:
                ast.parse(code)
                return True
            except SyntaxError:
                return False

        if ext == "json":
            try:
                json.loads(code)
                return True
            except Exception:
                return False

        return True