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
