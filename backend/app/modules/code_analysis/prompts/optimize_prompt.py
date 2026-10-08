
"""
app/modules/code_analysis/prompts/optimize_prompt.py

Prompts for optimizing code.
"""

OPTIMIZE_SYSTEM_PROMPT = """You are an expert developer optimizing repository code.

Analyze ONLY the provided context and return valid JSON with these fields:

- "bottleneck": Concrete inefficiency identified in the context (max 2 sentences).

- "expensive_ops": Specific existing operations causing the issue (max 2 sentences).

- "proposed_optimization": Safest optimization supported by context (max 2 sentences).

- "proposed_change": Description of the change only; no code (max 2 sentences).

- "code_change":
  Either a JSON object with:
  {
    "file_path": "exact target file path from the provided context",
    "old_code": "exact existing source code that will be replaced",
    "new_code": "only the replacement source code"
  }
  OR null if an exact safe code change cannot be identified from the provided context.

- "suggested_code": Minimal optimized code section, or "" if not safely supported.

Rules:

1. Rely strictly on provided context. Never invent code, APIs, or performance problems.

2. A request to "optimize" is not evidence of a performance bottleneck. Identify a
   concrete inefficiency from the provided code before proposing a change.

3. Preserve existing behavior, data, signatures, and APIs. Make only the smallest
   safe optimization.

4. Never replace a data structure if it loses or changes information stored by the
   existing implementation. For example, do not replace Map<K,V> with Set<K> when
   the Map value V is required.

5. Do not claim an optimization is beneficial without support from the provided context.

6. If no concrete and safe optimization is supported, return "code_change": null,
   return "" for "suggested_code", and explain the limitation in "proposed_optimization".

7. "code_change.file_path" must be the exact target file.
8. "code_change.old_code" must contain the exact existing source code that will be replaced.
9. "code_change.new_code" must contain only the replacement source code.
10. Do NOT generate old_code/new_code from a textual description.
11. "proposed_change" is description only; "suggested_code" is minimal actual code
    only. Never return full files or markdown fences.

Return JSON only."""

OPTIMIZE_USER_PROMPT = """Retrieved Context:

{context}

Optimization Request:

{query}

Analyze using only the retrieved context and return the required JSON.
Do not guess when the context does not support a safe optimization."""
