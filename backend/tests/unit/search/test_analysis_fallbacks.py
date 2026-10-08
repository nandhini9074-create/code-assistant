"""Tests for deterministic search-flow fallback behavior."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.enums import IntentType
from app.modules.search.domain.search_domain import RetrievedChunk, SearchContext
from app.modules.search.pipeline.code_analysis import CodeAnalysisStage
from app.modules.search.pipeline.final_triage import FinalTriageStage
from app.modules.search.pipeline.response_generation import ResponseGenerationStage


QUERY = "Fix the bug in suggest_time where valid appointment times are rejected"


def make_context() -> SearchContext:
    chunk = RetrievedChunk(
        chunk_hash="chunk-1",
        file_path="app/routers/appointments.py",
        content="def suggest_time(payload):\n    return available",
        score=0.91,
        metadata={
            "function_name": "suggest_time",
            "start_line": 239,
            "end_line": 287,
        },
    )
    return SearchContext(
        query=QUERY,
        repo_name="hospital_management",
        repo_owner="ashwathie",
        intent=IntentType.FIX_BUG,
        retrieved_chunks=[chunk],
        primary_chunk=chunk,
        target_symbol="suggest_time",
        llm_context="def suggest_time(payload):\n    return available",
    )


@pytest.mark.asyncio
async def test_analysis_failure_continues_with_conservative_fallback():
    context = make_context()
    service = SimpleNamespace(
        analyze=AsyncMock(side_effect=TimeoutError("provider timeout"))
    )

    await CodeAnalysisStage(service).execute(context)
    context.validation_status = "unavailable"
    await FinalTriageStage().execute(context)
    await ResponseGenerationStage().execute(context)

    response = context.final_response.model_dump()
    assert "failed" not in str(response).lower()
    assert "suggest_time" in response["suggestion"]
    assert "safe exact code change" in response["suggestion"]
    assert response["suggested_code"] is None
    assert response["confidence"] == "medium"


@pytest.mark.asyncio
async def test_suggestion_failure_preserves_safe_fallback():
    context = make_context()
    service = SimpleNamespace(
        analyze=AsyncMock(
            return_value={
                "error": "Code suggestion failed: invalid JSON",
                "current_behavior": "The target behavior is unclear.",
            }
        )
    )

    await CodeAnalysisStage(service).execute(context)
    context.validation_status = "unavailable"
    await FinalTriageStage().execute(context)
    await ResponseGenerationStage().execute(context)

    response = context.final_response.model_dump()
    assert "Code suggestion failed" not in str(response)
    assert "suggest_time" in response["suggestion"]
    assert response["suggested_code"] is None
    assert response["confidence"] == "medium"


@pytest.mark.asyncio
async def test_insufficient_evidence_is_low_confidence_without_patch():
    context = make_context()
    context.retrieved_chunks = []
    context.primary_chunk = None
    context.target_symbol = None
    context.llm_context = ""
    service = SimpleNamespace(
        analyze=AsyncMock(side_effect=ValueError("invalid JSON"))
    )

    await CodeAnalysisStage(service).execute(context)
    context.validation_status = "unavailable"
    await FinalTriageStage().execute(context)
    await ResponseGenerationStage().execute(context)

    response = context.final_response.model_dump()
    assert response["suggested_code"] is None
    assert response["confidence"] == "low"
    assert "safe exact code change" in response["suggestion"]


@pytest.mark.asyncio
async def test_successful_analysis_keeps_existing_result():
    context = make_context()
    analysis = {
        "current_behavior": "The parser rejects seconds.",
        "proposed_fix": "Accept the supported time format.",
        "proposed_change": "Update the parser format handling.",
        "suggested_code": "def suggest_time(payload):\n    return True",
    }
    service = SimpleNamespace(analyze=AsyncMock(return_value=analysis))

    await CodeAnalysisStage(service).execute(context)
    context.validation_status = "passed"
    context.validated = True
    await FinalTriageStage().execute(context)
    await ResponseGenerationStage().execute(context)

    response = context.final_response.model_dump()
    assert response["suggestion"] == "Accept the supported time format."
    assert response["proposed_change"] == "Update the parser format handling."
    assert response["suggested_code"] == analysis["suggested_code"]
    assert response["confidence"] == "high"


@pytest.mark.asyncio
async def test_response_includes_exact_code_change_and_patch():
    context = make_context()
    context.analysis_result = {
        "current_behavior": "The parser rejects seconds.",
        "proposed_fix": "Accept the supported time format.",
        "code_change": {
            "file_path": "app/routers/appointments.py",
            "old_code": '"error": "Booking can be done for the past date.",',
            "new_code": '"error": "Booking cannot be done for the past date.",',
        },
    }
    context.action_analysis = {
        "action_type": "BUG_REMEDIATION",
        "proposed_change": "Change the error message to state that booking cannot be done for a past date.",
        "code_change": {
            "file_path": "app/routers/appointments.py",
            "old_code": '"error": "Booking can be done for the past date.",',
            "new_code": '"error": "Booking cannot be done for the past date.",',
        },
    }
    context.suggested_patch = (
        '--- a/app/routers/appointments.py\n'
        '+++ b/app/routers/appointments.py\n'
        '@@ -1,1 +1,1 @@\n'
        '-                "error": "Booking can be done for the past date.",\n'
        '+                "error": "Booking cannot be done for the past date.",'
    )
    context.validation_status = "passed"
    context.validated = True

    await ResponseGenerationStage().execute(context)
    response = context.final_response.model_dump()

    assert response["code_change"]["file_path"] == "app/routers/appointments.py"
    assert "Booking cannot be done for the past date" in response["code_change"]["new_code"]
    assert "--- a/app/routers/appointments.py" in response["suggested_patch"]


@pytest.mark.asyncio
async def test_vulnerability_response_includes_all_grouped_package_patches():
    package_json = (
        '{\n  "dependencies": {\n'
        '    "axios": "1.6.2",\n'
        '    "lodash": "4.17.20"\n  }\n}'
    )
    updated_package_json = package_json.replace(
        '"axios": "1.6.2"', '"axios": "1.20.0"'
    ).replace('"lodash": "4.17.20"', '"lodash": "4.18.1"')
    per_package = [
        {
            "package": "axios",
            "old_code": '    "axios": "1.6.2",',
            "new_code": '    "axios": "1.20.0",',
        },
        {
            "package": "lodash",
            "old_code": '    "lodash": "4.17.20"',
            "new_code": '    "lodash": "4.18.1"',
        },
    ]
    context = SearchContext(
        query="Run npm audit",
        repo_name="demo-repo",
        intent=IntentType.FIX_VULNERABILITY,
        analysis_result={
            "analysis_status": "OK",
            "has_vulnerabilities": True,
            "vulnerability_count": 3,
            "confidence": "high",
            "affected_dependencies": [
                {
                    "package": "axios",
                    "current_version": "1.6.2",
                    "severity": "high",
                    "patched_version": "1.20.0",
                    "advisory_count": 2,
                },
                {
                    "package": "lodash",
                    "current_version": "4.17.20",
                    "severity": "critical",
                    "patched_version": "4.18.1",
                    "advisory_count": 1,
                },
            ],
            "code_change": {
                "file_path": "package.json",
                "old_code": package_json,
                "new_code": updated_package_json,
                "per_package": per_package,
            },
        },
        code_change={
            "file_path": "package.json",
            "old_code": package_json,
            "new_code": updated_package_json,
            "per_package": per_package,
        },
        suggested_patch=(
            "--- a/package.json\n+++ b/package.json\n"
            "@@ -1,6 +1,6 @@\n"
            '-    "axios": "1.6.2",\n+    "axios": "1.20.0",\n'
            '-    "lodash": "4.17.20"\n+    "lodash": "4.18.1"'
        ),
        patch_validation={"status": "passed", "checks": ["unified diff generated: PASS"]},
    )

    await ResponseGenerationStage().execute(context)
    response = context.final_response.model_dump()

    assert response["patch_validation"]["packages_fixed"] == ["axios", "lodash"]
    assert len(response["patch_validation"]["per_package_changes"]) == 2
    assert response["patch_validation"]["total_advisory_findings"] == 3
    assert response["patch_validation"]["affected_dependency_count"] == 2
    assert '"axios": "1.20.0"' in response["suggested_code"]
    assert '"lodash": "4.18.1"' in response["suggested_code"]
    assert "axios: 1.6.2 → 1.20.0" in response["formatted_output"]
    assert "lodash: 4.17.20 → 4.18.1" in response["formatted_output"]
    assert "All Detected Vulnerabilities" not in response["formatted_output"]
    assert response["patch_validation"]["repository_modified"] is False


@pytest.mark.asyncio
async def test_vulnerability_response_is_clean_when_audit_finds_no_issues():
    clean_result = "✓ No vulnerabilities found in project dependencies."
    context = SearchContext(
        query="Run npm audit",
        repo_name="demo-repo",
        intent=IntentType.FIX_VULNERABILITY,
        analysis_result={
            "analysis_status": "OK",
            "has_vulnerabilities": False,
            "confidence": "high",
        },
    )

    await ResponseGenerationStage().execute(context)
    response = context.final_response.model_dump()

    assert response["formatted_output"] == clean_result
    assert response["suggestion"] == clean_result
    assert response["patch_validation"]["repository_modified"] is False


@pytest.mark.asyncio
async def test_response_generation_formats_user_output():
    context = make_context()
    context.primary_chunk = RetrievedChunk(
        chunk_hash="chunk-app",
        file_path="app/crud/appointment.py",
        content=(
            "    if appointment_id:\n"
            "        continue\n"
            "    appt_start = appt.appointment_date\n"
            "    return True\n"
        ),
        score=0.95,
        metadata={
            "start_line": 6,
            "end_line": 9,
            "function_name": "is_slot_available",
        },
    )
    context.target_symbol = "is_slot_available"
    old_code = "appt_start = appt.appointment_date"
    new_code = (
        "appt_start = appt.appointment_date\n"
        "appt_end = appt_start + slot_duration\n"
        "if slot_start < appt_end and slot_end > appt_start:\n"
        "    return False"
    )
    context.analysis_result = {
        "current_behavior": "Slot check does not account for duration.",
        "proposed_fix": "Add duration comparison.",
        "code_change": {
            "file_path": "app/crud/appointment.py",
            "old_code": old_code,
            "new_code": new_code,
        },
    }
    context.action_analysis = {
        "action_type": "BUG_REMEDIATION",
        "proposed_change": "Add duration comparison to slot check.",
        "code_change": {
            "file_path": "app/crud/appointment.py",
            "old_code": old_code,
            "new_code": new_code,
        },
    }
    context.validation_status = "passed"
    context.validated = True

    from app.modules.search.pipeline.suggestion_patch import SuggestionPatchStage
    await SuggestionPatchStage().execute(context)
    await ResponseGenerationStage().execute(context)

    response = context.final_response.model_dump()
    assert response["code_change"]["start_line"] == 8
    assert response["code_change"]["end_line"] == 8
    assert response["code_change"]["operation"] == "replace"

    formatted = response["formatted_output"]
    assert formatted is not None
    assert "Target\nFile: app/crud/appointment.py" in formatted
    assert "Function: is_slot_available()" in formatted
    assert "Change location\nLines: 8–8\nOperation: replace" in formatted
    assert "Target verified: PASS" in formatted
    assert "Original code found exactly once: PASS" in formatted
    assert "Line location calculated from source: PASS" in formatted
    assert "Patch generated: PASS" in formatted
    assert "Repository modified: NO" in formatted

