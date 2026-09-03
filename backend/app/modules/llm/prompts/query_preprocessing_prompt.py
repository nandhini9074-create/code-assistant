"""
app/modules/llm/prompts/query_preprocessing_prompt.py
Prompts for query preprocessing.
"""

QUERY_PREPROCESSING_SYSTEM_PROMPT = """
Extract key identifiers, file names, and technical terms from the user query to optimize vector search.
Return a JSON object with:
- "keywords": A list of important keywords.
- "identifiers": A list of function, class, or variable names mentioned.
- "file_paths": A list of file names or paths mentioned.
"""

QUERY_PREPROCESSING_USER_PROMPT = """
Query: {query}
"""
