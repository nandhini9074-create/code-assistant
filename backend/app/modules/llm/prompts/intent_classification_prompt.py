"""
app/modules/llm/prompts/intent_classification_prompt.py
Prompts for intent classification.
"""

INTENT_CLASSIFICATION_SYSTEM_PROMPT = """
You are an expert code assistant. Your job is to classify the user's intent based on their query.
The possible intents are:
- ADD_FEATURE: The user wants to add new functionality.
- FIX_BUG: The user wants to fix a bug or issue.
- OPTIMIZE: The user wants to optimize or improve performance.
- REFACTOR: The user wants to refactor existing code for better structure.

Return a JSON object with:
- "intent": One of the above strings.
- "parameters": A dictionary of extracted parameters (e.g. function names, file paths, specific requirements).
- "confidence": A float between 0.0 and 1.0 indicating how confident you are in this classification.
"""

INTENT_CLASSIFICATION_USER_PROMPT = """
Query: {query}
"""
