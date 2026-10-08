"""
app/modules/search/pipeline/remediation_verification.py

Pipeline stage: Remediation Verification.

Verifies whether a vulnerable dependency in package.json has a verified
deterministic patched version from npm audit --json.
Never guesses patched versions. Never modifies repository files.
Produces an exact code_change object for package.json when safe and verified.
"""

from __future__ import annotations

import re
from typing import Any

from app.core.enums import IntentType
from app.core.logging import get_logger
from app.modules.search.domain.search_domain import SearchContext

logger = get_logger(__name__)

_SEVERITY_ORDER = {
    "critical": 4,
    "high": 3,
    "moderate": 2,
    "medium": 2,
    "low": 1,
    "info": 0,
    "unknown": -1,
}


class RemediationVerificationStage:
    """Stage that deterministically verifies remediation for package.json."""

    async def execute(self, context: SearchContext) -> None:
        if context.early_exit:
            logger.info(
                "remediation_verification_skipped",
                reason=context.early_exit,
            )
            return

        if context.intent != IntentType.FIX_VULNERABILITY:
            return

        vuln_data = context.vulnerability_data or {}
        audit_status = vuln_data.get("audit_status")

        # -------------------------------------------------------------
        # 1. Audit failed or incomplete
        # -------------------------------------------------------------
        if audit_status != "success":
            logger.warning(
                "remediation_verification_audit_failed",
                status=audit_status,
                error=vuln_data.get("audit_error"),
            )
            context.remediation_verified = False
            context.code_change = None
            context.action_analysis = None
            return

        # -------------------------------------------------------------
        # 2. No vulnerabilities reported
        # -------------------------------------------------------------
        if not vuln_data.get("has_vulnerabilities"):
            logger.info("remediation_verification_no_vulnerabilities")
            context.remediation_verified = True
            context.code_change = None
            context.action_analysis = None
            return

        # -------------------------------------------------------------
        # 3. Filter direct dependencies with verified patched versions
        # -------------------------------------------------------------
        vulns: list[dict[str, Any]] = (
            vuln_data.get("vulnerabilities")
            or vuln_data.get("all_vulnerabilities")
            or []
        )
        verified_direct_fixes = [
            v for v in vulns
            if v.get("is_direct") and v.get("patched_version")
        ]

        if not verified_direct_fixes:
            logger.info(
                "remediation_verification_no_verified_direct_fix",
                total_vulns=len(vulns),
            )
            context.remediation_verified = False
            context.code_change = None
            context.action_analysis = None
            return

        # -------------------------------------------------------------
        # 4. Select the target vulnerability to fix
        # -------------------------------------------------------------
        query_lower = (context.query or "").lower()

        query_matched = [
            v for v in verified_direct_fixes
            if str(v.get("package", "")).lower() in query_lower
        ]
        candidates = query_matched if query_matched else verified_direct_fixes
        candidates.sort(
            key=lambda v: (
                -_SEVERITY_ORDER.get(str(v.get("severity", "")).lower(), -1),
                str(v.get("package", "")).lower(),
                str(v.get("title", "")).lower(),
            )
        )
        selected = candidates[0]

        pkg_name = selected["package"]
        patched_version = str(selected["patched_version"]).strip()
        pkg_content = vuln_data.get("package_json_content") or ""

        # -------------------------------------------------------------
        # 5. Locate exact line in package.json
        # -------------------------------------------------------------
        code_change = self._build_package_json_change(
            pkg_content=pkg_content,
            pkg_name=pkg_name,
            patched_version=patched_version,
        )

        if not code_change:
            logger.warning(
                "remediation_verification_could_not_locate_dependency_line",
                package=pkg_name,
            )
            context.remediation_verified = False
            context.code_change = None
            context.action_analysis = None
            return

        # Store verified code change in context
        context.code_change = code_change
        context.remediation_verified = True
        context.target_symbol = None

        # Store in action_analysis and analysis_result for SuggestionPatchStage
        short_desc = f"Update {pkg_name} dependency in package.json to verified patched version {patched_version}."
        curr_behavior = (
            f"package.json specifies {pkg_name}@{selected.get('current_version', '')} "
            f"which falls within the vulnerable range {selected.get('vulnerable_range', '')}."
        )

        context.action_analysis = {
            "action_type": "BUG_REMEDIATION",
            "affected_target": {
                "file_path": "package.json",
                "symbol": None,
            },
            "proposed_change": short_desc,
            "suggested_code": code_change["new_code"],
            "code_change": code_change,
            "risk_level": "low",
        }

        context.analysis_result = {
            "analysis_status": "OK",
            "file_path": "package.json",
            "requirement": context.query,
            "issue_summary": selected.get("title") or f"{pkg_name} vulnerability",
            "current_behavior": curr_behavior,
            "proposed_fix": short_desc,
            "suggested_code": code_change["new_code"],
            "code_change": code_change,
            "confidence": "high",
            "selected_vulnerability": selected,
        }

        vuln_data["selected_vulnerability"] = selected
        context.vulnerability_data = vuln_data

        logger.info(
            "remediation_verification_successful",
            package=pkg_name,
            old_code=code_change["old_code"],
            new_code=code_change["new_code"],
            line=code_change["start_line"],
        )

    # -----------------------------------------------------------------
    # Helper: Build package.json change
    # -----------------------------------------------------------------
    def _build_package_json_change(
        self,
        pkg_content: str,
        pkg_name: str,
        patched_version: str,
    ) -> dict[str, Any] | None:
        """
        Locate the dependency line in package.json and produce exact old/new lines.
        Preserves indentation, version prefix (^, ~), and trailing comma.
        """
        lines = pkg_content.splitlines()
        # Pattern: "pkg_name": "^1.20.0",
        pattern = re.compile(
            r'^(\s*)"' + re.escape(pkg_name) + r'"\s*:\s*"([^"]+)"(,?)\s*$'
        )

        for idx, line in enumerate(lines, start=1):
            m = pattern.match(line)
            if m:
                indent = m.group(1)
                current_spec = m.group(2)
                trailing_comma = m.group(3)

                # Preserve prefix (^ or ~) if current_spec had one and patched_version does not
                prefix = ""
                if current_spec.startswith("^") and not patched_version.startswith("^"):
                    prefix = "^"
                elif current_spec.startswith("~") and not patched_version.startswith("~"):
                    prefix = "~"

                new_spec = f"{prefix}{patched_version}"
                new_line = f'{indent}"{pkg_name}": "{new_spec}"{trailing_comma}'

                if line == new_line:
                    # No actual change
                    return None

                return {
                    "file_path": "package.json",
                    "old_code": line,
                    "new_code": new_line,
                    "operation": "replace",
                    "start_line": idx,
                    "end_line": idx,
                    "symbol": None,
                }

        return None


# Export alias
RemediationVerification = RemediationVerificationStage
