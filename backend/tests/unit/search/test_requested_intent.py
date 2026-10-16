from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.core.enums import IntentType
from app.modules.search.domain.search_domain import SearchContext
from app.modules.search.pipeline.intent_classification import IntentClassificationStage
from app.modules.search.pipeline.response_generation import ResponseGenerationStage
from app.modules.search.schemas.search_schema import SearchRequest


def test_search_request_requires_a_supported_intent():
    payload = {
        "source": {
            "type": "git",
            "location": "https://github.com/example/project",
        },
        "query": "Check for vulnerabilities",
    }

    with pytest.raises(ValidationError):
        SearchRequest.model_validate(payload)

    request = SearchRequest.model_validate({**payload, "intent": "FIX_VULNERABILITY"})
    assert request.intent == IntentType.FIX_VULNERABILITY


@pytest.mark.asyncio
async def test_classification_uses_requested_intent_without_llm_call():
    llm_service = SimpleNamespace(
        classify_intent=AsyncMock(
            return_value=SimpleNamespace(
                intent=IntentType.RETRIEVE,
                parameters={"file_path": "src/auth.py"},
            )
        )
    )
    context = SearchContext(
        query="Check for vulnerabilities",
        requested_intent=IntentType.FIX_VULNERABILITY,
    )

    await IntentClassificationStage(llm_service).execute(context)

    assert context.intent == IntentType.FIX_VULNERABILITY
    assert context.intent_parameters == {"file_path": "src/auth.py"}
    llm_service.classify_intent.assert_awaited_once_with("Check for vulnerabilities")


def test_failure_response_handles_string_intent():
    context = SearchContext(
        query="Check for vulnerabilities",
        intent="FIX_VULNERABILITY",
    )

    response = ResponseGenerationStage.build_failure_response(
        context,
        RuntimeError("pipeline error"),
    )

    assert response.intent == "FIX_VULNERABILITY"
