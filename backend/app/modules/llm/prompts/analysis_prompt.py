"""
app/modules/llm/prompts/analysis_prompt.py
Base prompt templates for code analysis.
"""

from __future__ import annotations

# The base system prompt for all analysis tasks.
ANALYSIS_SYSTEM_PROMPT = """You are Code Explorer, an expert developer and codebase analyzer.
You are provided with a specific intent and a set of relevant code chunks retrieved from the repository.

CRITICAL RULES:
1. You must ONLY base your answer on the provided code chunks.
2. DO NOT invent, guess, or hallucinate files, functions, or classes that are not in the context.
3. If the provided context does not contain enough information to answer the prompt or fulfill the intent, you MUST state this clearly and safely.
4. Your response should be structured clearly, using markdown where appropriate, but remember that the final output format may be constrained by a JSON schema if requested.
"""

def build_user_prompt(intent: str, query: str, context_chunks: list[dict]) -> str:
    """
    Build the user prompt combining the query and the retrieved context.
    """
    prompt = f"Intent: {intent}\n"
    prompt += f"Query: {query}\n\n"
    prompt += "--- RETRIEVED CONTEXT ---\n"
    
    if not context_chunks:
        prompt += "(No context retrieved)\n"
    else:
        for idx, chunk in enumerate(context_chunks, 1):
            file_path = chunk.get("file_path", "unknown")
            start_line = chunk.get("start_line", "?")
            end_line = chunk.get("end_line", "?")
            code = chunk.get("raw_code", "")
            
            prompt += f"\nSnippet {idx}: {file_path} (Lines {start_line}-{end_line})\n"
            prompt += "```\n"
            prompt += f"{code}\n"
            prompt += "```\n"
            
    prompt += "\n--- END CONTEXT ---\n\n"
    prompt += "Based ONLY on the context above, provide your analysis."
    
    return prompt
