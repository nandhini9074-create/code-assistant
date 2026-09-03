"""
app/shared/utils/chunking_utils.py
Utilities for counting tokens and chunk management.
"""

def count_tokens(text: str) -> int:
    """
    Rough estimate of tokens in a string.
    In a real system, use tiktoken or similar based on the active model.
    Here we use a rough approximation (1 token ~= 4 chars).
    """
    if not text:
        return 0
    return max(1, len(text) // 4)
