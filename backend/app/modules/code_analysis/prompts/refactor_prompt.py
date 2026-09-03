"""
app/modules/code_analysis/prompts/refactor_prompt.py
Prompts for refactoring code.
"""

REFACTOR_SYSTEM_PROMPT = """
You are an expert developer helping to refactor a codebase.
Analyze the provided code context and the user's request.
Return a JSON object with:
- "code_smell": Description of the current code smells or structural issues.
- "duplication": Any duplicated logic found.
- "safe_refactoring_plan": Step-by-step plan to safely refactor the code.
"""

REFACTOR_USER_PROMPT = """
Context:
{context}

Request: {query}
"""
