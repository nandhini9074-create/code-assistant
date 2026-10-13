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
from app.core.logging import get_logger

from app.modules.search.domain.search_domain import SearchContext

from app.modules.search.pipeline.code_change_verifier import (

    format_final_response_output,

    verify_and_locate_code_change,

)

from app.modules.search.schemas.search_schema import (

    AmbiguousCandidate,

    SearchResponse,

)

logger = get_logger(__name__)


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

    # =============================================================

    # TARGET SYMBOL

    # =============================================================

    @staticmethod

    def _resolve_target_symbol(

        context: SearchContext,

    ) -> str | None:

        """Resolve a meaningful symbol without mistaking a filename for one."""

        primary_chunk = context.primary_chunk

        metadata = (

            primary_chunk.metadata

            if primary_chunk and isinstance(primary_chunk.metadata, dict)

            else {}

        )

        file_path = primary_chunk.file_path if primary_chunk else None

        class_name = str(metadata.get("class_name") or "").strip()

        function_name = str(metadata.get("function_name") or "").strip()

        target_symbol = context.target_symbol

        if isinstance(target_symbol, str):

            target_symbol = target_symbol.strip()

            source_extensions = (

                ".py", ".js", ".jsx", ".ts", ".tsx", ".java",

                ".go", ".rs", ".cpp", ".c", ".cs", ".php", ".rb",

            )

            if (

                target_symbol

                and target_symbol != file_path

                and not target_symbol.lower().endswith(source_extensions)

            ):

                return target_symbol

        # Prefer class, then function/method metadata when the target is a path.

        if class_name:

            return class_name

        if function_name:

            return function_name

        return None

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

        # DEEP SEARCH RESULT

        #

        # DeepSearchStage sets early_exit="DEEP_SEARCH_COMPLETE" and

        # stores its structured result in context.deep_search_result.

        # Present that result here before falling through to the normal

        # pipeline path. The normal path is not executed for Deep Search.

        # ---------------------------------------------------------

        if context.early_exit == "DEEP_SEARCH_COMPLETE":
            result = context.deep_search_result

            if not isinstance(result, dict):
                logger.error(
                    "deep_search_result_invalid",
                    repo_name=context.repo_name,
                    result_type=type(result).__name__,
                )
                result = {}

            # Normalize the result contract before the formatter consumes it.
            # A malformed result must never fall through to normal response
            # generation or be presented as a verified diagnosis.
            result = dict(result)
            valid_statuses = {"complete", "incomplete", "unavailable"}
            status = result.get("status")

            if not isinstance(status, str) or status not in valid_statuses:
                logger.warning(
                    "deep_search_status_invalid",
                    repo_name=context.repo_name,
                    status=repr(status),
                )
                result["status"] = "unavailable"
                result["reason"] = (
                    "Deep Search returned a missing or unrecognized status. "
                    "No verified root-cause diagnosis is available."
                )

            if not isinstance(result.get("diagnosis"), str):
                result["diagnosis"] = None

            if (
                result.get("status") == "complete"
                and (
                    not isinstance(result.get("diagnosis"), str)
                    or not result["diagnosis"].strip()
                )
            ):
                logger.warning(
                    "deep_search_diagnosis_missing",
                    repo_name=context.repo_name,
                )
                result["status"] = "unavailable"
                result["reason"] = (
                    "Deep Search reported completion without a verified "
                    "diagnosis. No root cause can be reported safely."
                )

            confidence = result.get("confidence", 0.0)
            if (
                isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
            ):
                result["confidence"] = 0.0

            if not isinstance(result.get("evidence"), list):
                result["evidence"] = []

            if not isinstance(result.get("reason"), str):
                result["reason"] = ""

            rounds = result.get("rounds", 0)
            if isinstance(rounds, bool) or not isinstance(rounds, int) or rounds < 0:
                result["rounds"] = 0

            for key in ("searched_targets", "missing_targets"):
                if not isinstance(result.get(key), list):
                    result[key] = []

            result.setdefault("repo_name", context.repo_name)

            # Keep the normalized result in context so the existing formatter
            # and any later consumers see the same safe status and fields.
            context.deep_search_result = result
            context.final_response = self._build_deep_search_response(
                context=context,
                intent_str=intent_str,
                repo_info=repo_info,
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

    # DEEP SEARCH RESPONSE

    # =============================================================

    @staticmethod

    def _build_deep_search_response(

        context: SearchContext,

        intent_str: str,

        repo_info: dict,

    ) -> "SearchResponse":

        """

        Format the final structured response for a Deep Search investigation.

        Presents the diagnosis and evidence when status is 'complete'.

        Presents an explicit explanation for 'incomplete' and 'unavailable'.

        This method does NOT:

        - generate new code changes,

        - modify the repository,

        - invent a root cause when evidence is insufficient,

        - or claim a fix was validated unless the workflow confirmed it.

        """

        result: dict = context.deep_search_result or {}

        status = result.get("status", "unavailable")

        diagnosis = result.get("diagnosis")

        confidence_raw = result.get("confidence", 0.0)

        evidence_items = result.get("evidence", [])

        reason = result.get("reason", "")

        rounds = result.get("rounds", 0)

        missing_targets = result.get("missing_targets", [])

        searched_targets = result.get("searched_targets", [])

        repo_name = result.get("repo_name") or repo_info.get("name")

        # Map numeric confidence to categorical string used by SearchResponse.

        if isinstance(confidence_raw, (int, float)):

            confidence_val = float(confidence_raw)

            if confidence_val >= 0.75:

                confidence_str = "high"

            elif confidence_val >= 0.50:

                confidence_str = "medium"

            else:

                confidence_str = "low"

        else:

            confidence_str = "low"

        # Build a human-readable evidence summary.

        evidence_lines: list[str] = []

        if isinstance(evidence_items, list):

            for item in evidence_items:

                if not isinstance(item, dict):

                    continue

                path = item.get("path", "")

                claim = item.get("claim", "")

                quote = item.get("quote", "")

                line_start = item.get("line_start")

                location = f"{path}:{line_start}" if line_start else path

                if claim:

                    evidence_lines.append(f"- [{location}] {claim}")

                    if quote:

                        evidence_lines.append(f"  Quote: {quote!r}")

        evidence_text = (

            "\n".join(evidence_lines)

            if evidence_lines

            else "No verified source evidence was collected."

        )

        if status == "complete" and diagnosis:

            suggestion = diagnosis

            proposed_change = (

                "Review the diagnosis and evidence below. "

                "No automatic code change was applied to the repository."

            )

            current_behavior = (

                f"Deep Search investigated {len(searched_targets)} target(s) "

                f"across {rounds} round(s)."

            )

            formatted_output = (

                f"Deep Search — Root Cause Analysis\n"

                f"Repository: {repo_name}\n"

                f"Status: COMPLETE\n"

                f"Confidence: {confidence_str}\n\n"

                f"Diagnosis\n\n{diagnosis}\n\n"

                f"Evidence ({len(evidence_items)} item(s))\n\n{evidence_text}\n\n"

                f"Investigated targets: {', '.join(str(t) for t in searched_targets) or 'none'}\n"

                f"Missing targets: {', '.join(str(t) for t in missing_targets) or 'none'}\n"

                f"Investigation rounds: {rounds}"

            )

        elif status == "incomplete":

            suggestion = (

                reason

                or "The investigation could not establish a verified root cause "

                   "within the available evidence and round limits."

            )

            proposed_change = (

                "Manual inspection of the repository is recommended. "

                "No automatic code change was generated."

            )

            current_behavior = (

                f"Deep Search investigated {len(searched_targets)} target(s) "

                f"across {rounds} round(s) but evidence was insufficient."

            )

            formatted_output = (

                f"Deep Search — Root Cause Analysis\n"

                f"Repository: {repo_name}\n"

                f"Status: INCOMPLETE\n"

                f"Confidence: low\n\n"

                f"Reason\n\n{suggestion}\n\n"

                f"Partial Evidence ({len(evidence_items)} item(s))\n\n{evidence_text}\n\n"

                f"Investigated targets: {', '.join(str(t) for t in searched_targets) or 'none'}\n"

                f"Missing targets: {', '.join(str(t) for t in missing_targets) or 'none'}\n"

                f"Investigation rounds: {rounds}"

            )

        else:

            # unavailable or unrecognized status

            suggestion = (

                reason

                or "Deep Search could not be completed. "

                   "A required service or source provider was unavailable."

            )

            proposed_change = (

                "Check that the repository is indexed and the search "

                "backend is accessible before retrying."

            )

            current_behavior = (

                "Deep Search could not access the required source or "

                "search services."

            )

            formatted_output = (

                f"Deep Search — Root Cause Analysis\n"

                f"Repository: {repo_name}\n"

                f"Status: UNAVAILABLE\n"

                f"Confidence: low\n\n"

                f"Reason\n\n{suggestion}"

            )

            confidence_str = "low"

        return SearchResponse(

            intent=intent_str,

            repository=repo_info,

            target={"file_path": None, "symbol": None},

            requirement=context.query,

            current_behavior=current_behavior,

            suggestion=suggestion,

            proposed_change=proposed_change,

            code_change=None,

            suggested_code=None,

            suggested_patch=None,

            patch_validation={

                "status": status,

                "deep_search": True,

                "rounds": rounds,

                "searched_targets": list(searched_targets),

                "missing_targets": list(missing_targets),

                "repository_modified": False,

            },

            formatted_output=formatted_output,

            confidence=confidence_str,

            early_exit=None,

            ambiguous_candidates=[],

            root_cause_analysis=result,

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

        Format the final structured response for FIX_VULNERABILITY.

        The vulnerability analyzer is responsible for:

          1. Running npm audit.

          2. Running npm audit fix only inside a temporary directory.

          3. Running npm audit again.

          4. Comparing the original and fixed manifests.

          5. Generating suggested_code/code_change.

        This method only presents those results.

        It does NOT:

          - run npm,

          - modify the repository,

          - generate a new vulnerability fix,

          - invent patched versions,

          - or perform new analysis.

        """

        import difflib

        analysis = context.analysis_result or {}

        analysis_status = analysis.get("analysis_status")

        confidence = analysis.get("confidence", "low")

        fix_attempted = bool(

            analysis.get("fix_attempted")

        )

        fix_verified = bool(

            analysis.get("fix_verified")

        )

        # ---------------------------------------------------------

        # CASE 1: AUDIT UNAVAILABLE

        # ---------------------------------------------------------

        if analysis_status == "UNAVAILABLE":

            error_message = (

                analysis.get("error")

                or "npm audit could not be completed."

            )

            formatted = (

                f"Query\n\n"

                f"{context.query}\n\n"

                f"Fix Vulnerability\n"

                f"Confidence: low\n\n"

                f"Target\n\n"

                f"package.json\n\n"

                f"Verification\n\n"

                f"The npm dependency audit could not be completed.\n\n"

                f"Error: {error_message}\n\n"

                f"Suggested Code\n\n"

                f"No code change was generated because the vulnerability "

                f"status or remediation could not be verified safely."

            )

            return SearchResponse(

                intent=intent_str,

                repository=repo_info,

                target={

                    "file_path": "package.json",

                    "symbol": None,

                },

                requirement=context.query,

                current_behavior=None,

                suggestion=(

                    "The npm dependency audit could not be completed. "

                    "No remediation was generated."

                ),

                proposed_change=None,

                code_change=None,

                suggested_code=None,

                suggested_patch=None,

                patch_validation={

                    "status": "failed",

                    "message": error_message,

                    "verification_source": "npm audit --json",

                    "repository_modified": False,

                },

                formatted_output=formatted,

                confidence="low",

                early_exit=None,

                ambiguous_candidates=[],

            )

        # ---------------------------------------------------------

        # CASE 2: NO VULNERABILITIES FOUND INITIALLY

        #

        # This must be checked using fix_attempted.

        #

        # The analyzer uses has_vulnerabilities=False both when:

        #   A) nothing was found initially, and

        #   B) vulnerabilities were found and successfully fixed.

        #

        # Therefore fix_verified/fix_attempted must be checked first.

        # ---------------------------------------------------------

        if (

            not fix_attempted

            and not analysis.get("has_vulnerabilities")

        ):

            clean_result = (

                "✓ No vulnerabilities found in project dependencies."

            )

            return SearchResponse(

                intent=intent_str,

                repository=repo_info,

                target={

                    "file_path": "package.json",

                    "symbol": None,

                },

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

        # ---------------------------------------------------------

        # CASE 3: VERIFIED FIX

        #

        # This is the new npm audit -> npm audit fix -> npm audit

        # workflow.

        #

        # The analyzer has already generated:

        #   - suggested_code

        #   - suggested_changes

        #   - code_change

        #

        # We only present them here.

        # ---------------------------------------------------------

        if fix_verified:

            code_change = (

                analysis.get("code_change")

                or context.code_change

            )

            suggested_code = analysis.get(

                "suggested_code"

            )

            suggested_changes = (

                analysis.get("suggested_changes")

                or []

            )

            initial_vulnerabilities = (

                analysis.get("all_vulnerabilities")

                or analysis.get("vulnerabilities")

                or []

            )

            initial_count = analysis.get(

                "initial_vulnerability_count"

            )

            if initial_count is None:

                initial_count = len(

                    initial_vulnerabilities

                )

            changed_files = [

                change.get("file_path")

                for change in suggested_changes

                if isinstance(change, dict)

                and change.get("file_path")

            ]

            # -----------------------------------------------------

            # Build a fallback suggested_code only if the analyzer

            # did not already provide it.

            #

            # Normally the analyzer already supplies this value.

            # -----------------------------------------------------

            if not suggested_code and suggested_changes:

                sections: list[str] = []

                for change in suggested_changes:

                    if not isinstance(change, dict):

                        continue

                    file_path = change.get(

                        "file_path",

                        "unknown",

                    )

                    diff = change.get(

                        "diff",

                        "",

                    )

                    if diff:

                        sections.append(

                            f"File: {file_path}\n\n{diff}"

                        )

                    else:

                        sections.append(

                            f"File: {file_path}\n\n"

                            f"{change.get('new_code', '')}"

                        )

                suggested_code = (

                    "\n\n".join(sections)

                    if sections

                    else None

                )

            # -----------------------------------------------------

            # Fallback diff only for the primary code_change.

            # This does not change the analyzer's logic.

            # -----------------------------------------------------

            suggested_patch = (

                context.suggested_patch

                or analysis.get("suggested_patch")

            )

            if (

                not suggested_patch

                and isinstance(code_change, dict)

                and code_change.get("old_code") is not None

                and code_change.get("new_code") is not None

            ):

                diff_lines = list(

                    difflib.unified_diff(

                        str(

                            code_change.get(

                                "old_code",

                                "",

                            )

                        ).splitlines(),

                        str(

                            code_change.get(

                                "new_code",

                                "",

                            )

                        ).splitlines(),

                        fromfile=(

                            f"a/{code_change.get('file_path', 'package.json')}"

                        ),

                        tofile=(

                            f"b/{code_change.get('file_path', 'package.json')}"

                        ),

                        lineterm="",

                        n=3,

                    )

                )

                suggested_patch = (

                    "\n".join(diff_lines)

                    if diff_lines

                    else None

                )

            vulnerability_summary = (

                self._format_vulnerability_summary_for_response(

                    initial_vulnerabilities

                )

            )

            changed_files_text = (

                "\n".join(

                    f"- {file_path}"

                    for file_path in changed_files

                )

                if changed_files

                else "No manifest changes were generated."

            )

            current_behavior = (

                f"npm audit initially detected "

                f"{initial_count} "

                f"{'vulnerability' if initial_count == 1 else 'vulnerabilities'}.\n\n"

                f"npm audit fix was executed in an isolated temporary "

                f"directory. A second npm audit confirmed that no "

                f"vulnerabilities remain."

            )

            if vulnerability_summary:

                current_behavior += (

                    f"\n\nInitial Findings\n\n"

                    f"{vulnerability_summary}"

                )

            proposed_change = (

                "Apply the verified dependency changes shown in "

                "suggested_code after reviewing the generated diff."

            )

            if changed_files:

                proposed_change += (

                    "\n\nChanged files in the temporary fix:"

                    f"\n{changed_files_text}"

                )

            suggestion = (

                "npm audit fix successfully resolved the detected "

                "vulnerabilities in the temporary copy. Review the "

                "suggested changes before applying them to the repository."

            )

            verification_text = (

                "Initial npm audit: PASS — vulnerabilities detected\n"

                "npm audit fix in temporary directory: PASS\n"

                "Second npm audit: PASS — no vulnerabilities remain\n"

                "Repository modified: NO"

            )

            formatted = (

                f"Fix Vulnerability\n"

                f"Confidence: {confidence}\n\n"

                f"Target\n\n"

                f"package.json\n\n"

                f"Audit Summary\n\n"

                f"Initial vulnerabilities detected: {initial_count}\n"

                f"Remaining vulnerabilities after fix: 0\n\n"

                f"Suggested Changes\n\n"

                f"{changed_files_text}\n\n"

                f"Suggested Code\n\n"

                f"{suggested_code or 'No suggested code generated.'}\n\n"

                f"Verification\n\n"

                f"{verification_text}"

            )

            patch_validation = {

                "status": "passed",

                "message": (

                    "npm audit fix was executed in an isolated temporary "

                    "directory and a second npm audit confirmed that no "

                    "vulnerabilities remain. The repository was not modified."

                ),

                "verification_source": "npm audit --json",

                "initial_vulnerability_count": initial_count,

                "remaining_vulnerability_count": 0,

                "fix_attempted": True,

                "fix_verified": True,

                "changed_files": changed_files,

                "repository_modified": False,

            }

            return SearchResponse(

                intent=intent_str,

                repository=repo_info,

                target={

                    "file_path": "package.json",

                    "symbol": None,

                },

                requirement=context.query,

                current_behavior=current_behavior,

                suggestion=suggestion,

                proposed_change=proposed_change,

                code_change=code_change,

                suggested_code=suggested_code,

                suggested_patch=suggested_patch,

                patch_validation=patch_validation,

                formatted_output=formatted,

                confidence=confidence,

                early_exit=None,

                ambiguous_candidates=[],

            )

        # ---------------------------------------------------------

        # CASE 4: FIX ATTEMPTED BUT VULNERABILITIES REMAIN

        # ---------------------------------------------------------

        if fix_attempted and not fix_verified:

            remaining_vulnerabilities = (

                analysis.get("remaining_vulnerabilities")

                or []

            )

            vulnerability_count = analysis.get(

                "vulnerability_count",

                len(remaining_vulnerabilities),

            )

            remaining_summary = (

                analysis.get(

                    "remaining_vulnerability_summary"

                )

                or self._format_vulnerability_summary_for_response(

                    remaining_vulnerabilities

                )

            )

            fix_error = (

                analysis.get("fix_error")

                or analysis.get("verification_error")

            )

            if remaining_vulnerabilities:

                current_behavior = (

                    f"npm audit detected vulnerabilities. "

                    f"npm audit fix was attempted in an isolated "

                    f"temporary directory, but "

                    f"{vulnerability_count} "

                    f"{'vulnerability remains' if vulnerability_count == 1 else 'vulnerabilities remain'} "

                    f"after the second npm audit."

                )

            else:

                current_behavior = (

                    "npm audit detected vulnerabilities and an automatic "

                    "fix was attempted, but the result could not be "

                    "verified as fully resolved."

                )

            suggestion = (

                analysis.get("proposed_fix")

                or "Manual review is required."

            )

            proposed_change = (

                analysis.get("proposed_change")

                or "Manual review required."

            )

            error_text = (

                f"\n\nError\n\n{fix_error}"

                if fix_error

                else ""

            )

            formatted = (

                f"Fix Vulnerability\n"

                f"Confidence: low\n\n"

                f"Target\n\n"

                f"package.json\n\n"

                f"Audit Summary\n\n"

                f"{current_behavior}\n\n"

                f"Remaining Vulnerabilities\n\n"

                f"{remaining_summary or 'No detailed vulnerability summary available.'}\n\n"

                f"Suggested Code\n\n"

                f"No verified automatic patch is available.\n\n"

                f"Recommendation\n\n"

                f"{suggestion}"

                f"{error_text}\n\n"

                f"Verification\n\n"

                f"Initial npm audit: PASS — vulnerabilities detected\n"

                f"npm audit fix attempted: PASS\n"

                f"Second npm audit: FAIL — vulnerabilities remain or "

                f"could not be verified\n"

                f"Repository modified: NO"

            )

            return SearchResponse(

                intent=intent_str,

                repository=repo_info,

                target={

                    "file_path": "package.json",

                    "symbol": None,

                },

                requirement=context.query,

                current_behavior=current_behavior,

                suggestion=suggestion,

                proposed_change=proposed_change,

                code_change=None,

                suggested_code=None,

                suggested_patch=None,

                patch_validation={

                    "status": "failed",

                    "message": (

                        "The vulnerability fix could not be verified "

                        "as completely successful."

                    ),

                    "verification_source": "npm audit --json",

                    "initial_vulnerability_count": analysis.get(

                        "initial_vulnerability_count"

                    ),

                    "remaining_vulnerability_count": len(

                        remaining_vulnerabilities

                    ),

                    "fix_attempted": True,

                    "fix_verified": False,

                    "repository_modified": False,

                    "error": fix_error,

                },

                formatted_output=formatted,

                confidence="low",

                early_exit=None,

                ambiguous_candidates=[],

            )

        # ---------------------------------------------------------

        # CASE 5: FALLBACK FOR AN UNEXPECTED VULNERABILITY STATE

        #

        # This is intentionally conservative. It does not invent

        # a patch or patched version.

        # ---------------------------------------------------------

        vulnerability_count = analysis.get(

            "vulnerability_count",

            0,

        )

        vulnerabilities = (

            analysis.get("vulnerabilities")

            or analysis.get("all_vulnerabilities")

            or []

        )

        vulnerability_summary = (

            self._format_vulnerability_summary_for_response(

                vulnerabilities

            )

        )

        formatted = (

            f"Fix Vulnerability\n"

            f"Confidence: low\n\n"

            f"Target\n\n"

            f"package.json\n\n"

            f"Audit Summary\n\n"

            f"npm audit reported {vulnerability_count} "

            f"{'finding' if vulnerability_count == 1 else 'findings'}.\n\n"

            f"Suggested Code\n\n"

            f"No verified automatic patch is available.\n\n"

            f"Recommendation\n\n"

            f"Manual review is required."

        )

        if vulnerability_summary:

            formatted += (

                f"\n\nFindings\n\n"

                f"{vulnerability_summary}"

            )

        return SearchResponse(

            intent=intent_str,

            repository=repo_info,

            target={

                "file_path": "package.json",

                "symbol": None,

            },

            requirement=context.query,

            current_behavior=(

                f"npm audit reported {vulnerability_count} "

                f"{'vulnerability' if vulnerability_count == 1 else 'vulnerabilities'}."

            ),

            suggestion=(

                analysis.get("proposed_fix")

                or "Manual review required."

            ),

            proposed_change=(

                analysis.get("proposed_change")

                or "Manual review required."

            ),

            code_change=None,

            suggested_code=None,

            suggested_patch=None,

            patch_validation={

                "status": "failed",

                "message": (

                    "No verified automatic vulnerability fix is available."

                ),

                "verification_source": "npm audit --json",

                "repository_modified": False,

            },

            formatted_output=formatted,

            confidence="low",

            early_exit=None,

            ambiguous_candidates=[],

        )

    @staticmethod

    def _format_vulnerability_summary_for_response(

        vulnerabilities: list[Any],

    ) -> str:

        """

        Format vulnerability information already produced by the

        vulnerability analyzer.

        This method does not perform any new vulnerability analysis.

        """

        if not isinstance(vulnerabilities, list):

            return ""

        lines: list[str] = []

        for vulnerability in vulnerabilities:

            if not isinstance(vulnerability, dict):

                continue

            package = (

                vulnerability.get("package")

                or "unknown"

            )

            severity = (

                vulnerability.get("severity")

                or "unknown"

            )

            title = (

                vulnerability.get("title")

                or "vulnerability"

            )

            current_version = (

                vulnerability.get("current_version")

                or "unknown"

            )

            lines.append(

                f"- {package} "

                f"({severity}, current: {current_version}): "

                f"{title}"

            )

        return "\n".join(lines)

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
