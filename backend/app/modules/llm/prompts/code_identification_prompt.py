"""
app/modules/llm/prompts/code_identification_prompt.py
Prompts for identifying code elements.
"""

CODE_IDENTIFICATION_SYSTEM_PROMPT = """
Identify specific code elements mentioned in the user query that are present in the provided context chunks.
Return a JSON array of objects with:
- "name": The exact name of the element.
- "type": One of 'function', 'class', 'variable', 'file', 'unknown'.
- "context": A brief description of how it is used.
"""

CODE_IDENTIFICATION_USER_PROMPT = """
Context chunks:
{context}

Query: {query}
"""
