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
from app.modules.code_analysis.prompts.optimize_prompt import (
    OPTIMIZE_SYSTEM_PROMPT,
    OPTIMIZE_USER_PROMPT,
)
from app.modules.code_analysis.prompts.refactor_prompt import (
    REFACTOR_SYSTEM_PROMPT,
    REFACTOR_USER_PROMPT,
)

__all__ = [
    "ADD_FEATURE_SYSTEM_PROMPT",
    "ADD_FEATURE_USER_PROMPT",
    "FIX_BUG_SYSTEM_PROMPT",
    "FIX_BUG_USER_PROMPT",
    "OPTIMIZE_SYSTEM_PROMPT",
    "OPTIMIZE_USER_PROMPT",
    "REFACTOR_SYSTEM_PROMPT",
    "REFACTOR_USER_PROMPT",
]
