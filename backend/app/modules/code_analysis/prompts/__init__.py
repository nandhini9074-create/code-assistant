"""
app/modules/code_analysis/prompts/__init__.py
"""
from app.modules.code_analysis.prompts.add_feature_prompt import (
    ADD_FEATURE_SYSTEM_PROMPT,
    ADD_FEATURE_USER_PROMPT,
)
from app.modules.code_analysis.prompts.fix_bug_prompt import (
    FIX_BUG_SYSTEM_PROMPT,
    FIX_BUG_USER_PROMPT,
)


__all__ = [
    "ADD_FEATURE_SYSTEM_PROMPT",
    "ADD_FEATURE_USER_PROMPT",
    "FIX_BUG_SYSTEM_PROMPT",
    "FIX_BUG_USER_PROMPT",
]
