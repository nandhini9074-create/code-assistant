"""Utilities for interpreting npm audit JSON output."""

from __future__ import annotations

from typing import Any


def parse_npm_audit_vulnerabilities(
    audit_data: dict[str, Any],
    direct_deps: dict[str, str],
) -> list[dict[str, Any]]:
    """Normalize npm audit vulnerability entries without inferring fixes."""
    results: list[dict[str, Any]] = []
    vulnerabilities = audit_data.get("vulnerabilities")
    if not isinstance(vulnerabilities, dict):
        return results

    for package_name, vulnerability in vulnerabilities.items():
        if not isinstance(vulnerability, dict):
            continue

        pkg_severity = vulnerability.get("severity") or "unknown"
        pkg_range = vulnerability.get("range") or "unknown"
        is_direct = bool(
            vulnerability.get("isDirect") or package_name in direct_deps
        )
        fix_available = vulnerability.get("fixAvailable")
        patched_version = None
        if isinstance(fix_available, dict):
            version = fix_available.get("version")
            if isinstance(version, str) and version.strip():
                patched_version = version.strip()

        current_version = direct_deps.get(package_name, "unknown")
        via_raw = vulnerability.get("via")
        via_list = via_raw if isinstance(via_raw, list) else []
        advisories = [item for item in via_list if isinstance(item, dict)]

        if advisories:
            for advisory in advisories:
                title = str(
                    advisory.get("title") or f"{package_name} vulnerability"
                )
                severity = str(advisory.get("severity") or pkg_severity)
                affected_range = str(advisory.get("range") or pkg_range)
                url = advisory.get("url")
                record: dict[str, Any] = {
                    "package": package_name,
                    "current_version": current_version,
                    "severity": severity,
                    "vulnerable_range": affected_range,
                    "patched_version": patched_version,
                    "is_direct": is_direct,
                    "remediation": (
                        f"Upgrade {package_name} to {patched_version}"
                        if patched_version
                        else "No verified exact fix available"
                    ),
                    "title": title,
                    "urls": [str(url)] if url else [],
                    "fix_available": fix_available,
                }
                if advisory.get("source") is not None:
                    record["advisory_id"] = str(advisory["source"])
                results.append(record)
        else:
            titles = [
                str(item["title"])
                for item in via_list
                if isinstance(item, dict) and item.get("title")
            ]
            urls = [
                str(item["url"])
                for item in via_list
                if isinstance(item, dict) and item.get("url")
            ]
            results.append(
                {
                    "package": package_name,
                    "current_version": current_version,
                    "severity": pkg_severity,
                    "vulnerable_range": pkg_range,
                    "patched_version": patched_version,
                    "is_direct": is_direct,
                    "remediation": (
                        f"Upgrade {package_name} to {patched_version}"
                        if patched_version
                        else "No verified exact fix available"
                    ),
                    "title": "; ".join(dict.fromkeys(titles))
                    if titles
                    else f"{package_name} vulnerability",
                    "urls": urls,
                    "fix_available": fix_available,
                }
            )
    return results