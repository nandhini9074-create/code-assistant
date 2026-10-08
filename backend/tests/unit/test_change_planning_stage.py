import pytest

from app.core.enums import IntentType
from app.modules.search.domain.search_domain import SearchContext
from app.modules.search.pipeline.change_planning import ChangePlanningStage


@pytest.mark.asyncio
async def test_change_planning_stage_builds_plan_for_feature_requests() -> None:
    context = SearchContext(
        query="Add a feature to display a bye message",
        repo_name="demo-repo",
        intent=IntentType.ADD_FEATURE,
        analysis_result={
            "analysis_status": "OK",
            "proposed_change": {
                "description": "Render a bye message in the UI",
                "implementation_steps": [
                    "Update the view component",
                    "Attach the event handler",
                ],
            },
        },
        action_analysis={
            "action_type": "FEATURE_IMPLEMENTATION",
            "proposed_change": "Render a bye message in the UI",
            "risk_level": "medium",
        },
    )

    await ChangePlanningStage().execute(context)

    assert context.change_plan is not None
    assert context.change_plan["change_type"] == "FEATURE_IMPLEMENTATION"
    assert context.change_plan["summary"] == "Render a bye message in the UI"
    assert len(context.change_plan["implementation_steps"]) >= 2
