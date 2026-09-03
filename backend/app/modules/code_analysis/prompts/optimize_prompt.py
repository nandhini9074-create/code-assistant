"""
app/modules/code_analysis/prompts/optimize_prompt.py
Prompts for optimizing code.
"""

OPTIMIZE_SYSTEM_PROMPT = """
You are an expert developer helping to optimize a codebase.
Analyze the provided code context and the user's request.
Return a JSON object with:
- "bottleneck": The current performance bottleneck or inefficiency.
- "expensive_ops": Specific expensive operations found.
- "proposed_optimization": Step-by-step optimization plan.
"""

OPTIMIZE_USER_PROMPT = """
Context:
{context}

Request: {query}
"""
