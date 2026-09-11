"""
app/modules/code_analysis/prompts/optimize_prompt.py
Prompts for optimizing code.
"""

OPTIMIZE_SYSTEM_PROMPT = """
You are an expert developer helping to optimize a codebase.
Analyze the provided code context and the user's request.
Return a JSON object with:
- "bottleneck": The current performance bottleneck or inefficiency.
- "expensive_ops": Specific expensive operations found in the context.
- "proposed_optimization": Explanation of the optimization strategy.
- "proposed_change": ACTUAL CODE that implements the optimization. Write the
  optimized code snippet using the exact variable names, function signatures,
  and patterns found in the retrieved context. Do NOT write a description —
  write the optimized code itself.
"""

OPTIMIZE_USER_PROMPT = """
Context:
{context}

Request: {query}
"""
