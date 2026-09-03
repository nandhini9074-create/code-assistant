"""
app/modules/llm/prompts/__init__.py
"""
from app.modules.llm.prompts.code_identification_prompt import (
    CODE_IDENTIFICATION_SYSTEM_PROMPT,
    CODE_IDENTIFICATION_USER_PROMPT,
)
from app.modules.llm.prompts.intent_classification_prompt import (
    INTENT_CLASSIFICATION_SYSTEM_PROMPT,
    INTENT_CLASSIFICATION_USER_PROMPT,
)
from app.modules.llm.prompts.query_preprocessing_prompt import (
    QUERY_PREPROCESSING_SYSTEM_PROMPT,
    QUERY_PREPROCESSING_USER_PROMPT,
)

__all__ = [
    "CODE_IDENTIFICATION_SYSTEM_PROMPT",
    "CODE_IDENTIFICATION_USER_PROMPT",
    "INTENT_CLASSIFICATION_SYSTEM_PROMPT",
    "INTENT_CLASSIFICATION_USER_PROMPT",
    "QUERY_PREPROCESSING_SYSTEM_PROMPT",
    "QUERY_PREPROCESSING_USER_PROMPT",
]
