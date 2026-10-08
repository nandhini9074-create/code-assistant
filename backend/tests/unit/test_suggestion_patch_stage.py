from types import SimpleNamespace

import pytest

from app.core.enums import IntentType
from app.modules.search.domain.search_domain import SearchContext
from app.modules.search.pipeline.suggestion_patch import SuggestionPatchStage


@pytest.mark.asyncio
async def test_suggestion_patch_stage_builds_in_memory_patch() -> None:
    context = SearchContext(
        query="Fix the bug in this code",
        repo_name="demo-repo",
        intent=IntentType.FIX_BUG,
        primary_chunk=SimpleNamespace(
            file_path="app/services/example.py",
            code="print('before')\n",
            metadata={"start_line": 1, "end_line": 1},
        ),
        analysis_result={
            "analysis_status": "OK",
            "proposed_fix": "Add the missing guard before the processing call.",
            "suggested_code": "print('after')\n",
        },
        action_analysis={
            "action_type": "BUG_REMEDIATION",
            "proposed_change": "Add the missing guard before the processing call.",
            "risk_level": "low",
            "suggested_code": "print('after')\n",
        },
    )

    await SuggestionPatchStage().execute(context)

    assert context.suggested_patch is not None
    assert "--- a/app/services/example.py" in context.suggested_patch
    assert context.patch_validation is not None
    assert context.patch_validation["status"] == "passed"


@pytest.mark.asyncio
async def test_suggestion_patch_stage_uses_exact_code_change_when_present() -> None:
    context = SearchContext(
        query="Fix the incorrect past-date validation error message.",
        repo_name="hospital_management",
        repo_owner="ashwathie",
        intent=IntentType.FIX_BUG,
        primary_chunk=SimpleNamespace(
            file_path="app/routers/appointments.py",
            code='"error": "Booking can be done for the past date.",',
            metadata={"start_line": 1, "end_line": 1},
        ),
        analysis_result={
            "analysis_status": "OK",
            "code_change": {
                "file_path": "app/routers/appointments.py",
                "old_code": '"error": "Booking can be done for the past date.",',
                "new_code": '"error": "Booking cannot be done for the past date.",',
            },
        },
        action_analysis={
            "action_type": "BUG_REMEDIATION",
            "proposed_change": "Fix the incorrect past-date validation error message.",
            "risk_level": "low",
            "code_change": {
                "file_path": "app/routers/appointments.py",
                "old_code": '"error": "Booking can be done for the past date.",',
                "new_code": '"error": "Booking cannot be done for the past date.",',
            },
        },
    )

    await SuggestionPatchStage().execute(context)

    assert context.suggested_patch is not None
    assert "Booking cannot be done for the past date" in context.suggested_patch
    assert context.patch_validation is not None
    assert context.patch_validation["status"] == "passed"
    assert context.code_change["start_line"] == 1
    assert context.code_change["end_line"] == 1
    assert context.code_change["operation"] == "replace"


@pytest.mark.asyncio
async def test_suggestion_patch_stage_calculates_exact_line_location_from_source() -> None:
    source_snippet = (
        "    if appointment_id:\n"
        "        continue\n"
        "    appt_start = appt.appointment_date\n"
        "    return True\n"
    )
    context = SearchContext(
        query="Fix appointment slot check",
        repo_name="demo-repo",
        intent=IntentType.FIX_BUG,
        primary_chunk=SimpleNamespace(
            file_path="app/crud/appointment.py",
            code=source_snippet,
            metadata={
                "start_line": 6,
                "end_line": 9,
                "function_name": "is_slot_available",
            },
        ),
        analysis_result={
            "analysis_status": "OK",
            "code_change": {
                "file_path": "app/crud/appointment.py",
                "old_code": "appt_start = appt.appointment_date",
                "new_code": (
                    "appt_start = appt.appointment_date\n"
                    "appt_end = appt_start + slot_duration\n"
                    "if slot_start < appt_end and slot_end > appt_start:\n"
                    "    return False"
                ),
            },
        },
        action_analysis={
            "action_type": "BUG_REMEDIATION",
            "code_change": {
                "file_path": "app/crud/appointment.py",
                "old_code": "appt_start = appt.appointment_date",
                "new_code": (
                    "appt_start = appt.appointment_date\n"
                    "appt_end = appt_start + slot_duration\n"
                    "if slot_start < appt_end and slot_end > appt_start:\n"
                    "    return False"
                ),
            },
        },
    )

    await SuggestionPatchStage().execute(context)

    assert context.suggested_patch is not None
    assert "@@ -8 +8,4 @@" in context.suggested_patch
    assert context.code_change["start_line"] == 8
    assert context.code_change["end_line"] == 8
    assert context.code_change["operation"] == "replace"
    assert context.code_change["symbol"] == "is_slot_available"
    assert context.patch_validation["status"] == "passed"


@pytest.mark.asyncio
async def test_suggestion_patch_stage_multiline_end_line_calculation() -> None:
    source_snippet = (
        "    if appointment_id:\n"
        "        continue\n"
        "    appt_start = appt.appointment_date\n"
        "    appt_end = appt.appointment_end\n"
        "    return True\n"
    )
    context = SearchContext(
        query="Fix appointment date handling",
        repo_name="demo-repo",
        intent=IntentType.FIX_BUG,
        primary_chunk=SimpleNamespace(
            file_path="app/crud/appointment.py",
            code=source_snippet,
            metadata={"start_line": 6, "end_line": 10},
        ),
        analysis_result={
            "analysis_status": "OK",
            "code_change": {
                "file_path": "app/crud/appointment.py",
                "old_code": "appt_start = appt.appointment_date\n    appt_end = appt.appointment_end\n    return True",
                "new_code": "return False",
            },
        },
    )

    await SuggestionPatchStage().execute(context)

    assert context.suggested_patch is not None
    assert context.code_change["start_line"] == 8
    assert context.code_change["end_line"] == 10
    assert context.code_change["operation"] == "replace"


@pytest.mark.asyncio
async def test_suggestion_patch_stage_rejects_when_old_code_not_found() -> None:
    context = SearchContext(
        query="Fix something non-existent",
        repo_name="demo-repo",
        intent=IntentType.FIX_BUG,
        primary_chunk=SimpleNamespace(
            file_path="app/crud/appointment.py",
            code="def foo():\n    return 42\n",
            metadata={"start_line": 1, "end_line": 2},
        ),
        analysis_result={
            "analysis_status": "OK",
            "code_change": {
                "file_path": "app/crud/appointment.py",
                "old_code": "non_existent_code = 123",
                "new_code": "return 0",
            },
        },
    )

    await SuggestionPatchStage().execute(context)

    assert context.suggested_patch is None
    assert context.patch_validation["status"] == "failed"
    assert any("not found" in err.lower() for err in context.patch_validation["warnings"])


@pytest.mark.asyncio
async def test_suggestion_patch_stage_rejects_ambiguous_matches() -> None:
    context = SearchContext(
        query="Fix recurring line",
        repo_name="demo-repo",
        intent=IntentType.FIX_BUG,
        primary_chunk=SimpleNamespace(
            file_path="app/crud/appointment.py",
            code="x = 1\nx = 1\n",
            metadata={"start_line": 1, "end_line": 2},
        ),
        analysis_result={
            "analysis_status": "OK",
            "code_change": {
                "file_path": "app/crud/appointment.py",
                "old_code": "x = 1",
                "new_code": "x = 2",
            },
        },
    )

    await SuggestionPatchStage().execute(context)

    assert context.suggested_patch is None
    assert context.patch_validation["status"] == "failed"
    assert any("ambiguous" in err.lower() for err in context.patch_validation["warnings"])

