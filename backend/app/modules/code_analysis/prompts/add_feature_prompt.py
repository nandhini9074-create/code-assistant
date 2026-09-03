"""
app/modules/code_analysis/prompts/add_feature_prompt.py
Prompts for adding a feature.
"""

ADD_FEATURE_SYSTEM_PROMPT = """
You are an expert developer helping to add a feature to a codebase.
Analyze the provided code context and the user's request.
Return a JSON object with:
- "existing_implementation": Brief description of current state.
- "required_changes": List of steps to implement the feature.
- "affected_files": List of files that need to be modified.
- "risks": Any potential side effects or risks.
"""

ADD_FEATURE_USER_PROMPT = """
Context:
{context}

Request: {query}
"""
