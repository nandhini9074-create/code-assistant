"""
app/modules/llm/validators/llm_response_validator.py
Validators for LLM responses.
"""

from typing import Any


def validate_intent_classification(response: dict[str, Any]) -> bool:
    """Validate that the intent classification response has the required fields."""
    required_fields = ["intent", "parameters", "confidence"]
    return all(field in response for field in required_fields)


def validate_code_identification(response: list[dict[str, Any]]) -> bool:
    """Validate that the code identification response has the required fields."""
    if not isinstance(response, list):
        return False
        
    required_fields = ["name", "type"]
    return all(
        isinstance(item, dict) and all(field in item for field in required_fields)
        for item in response
    )
