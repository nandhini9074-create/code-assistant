"""
app/modules/search/pipeline/context_builder.py
Pipeline stage: Context builder.
"""

from app.modules.search.domain.search_domain import SearchContext


class ContextBuilderStage:
    async def execute(self, context: SearchContext) -> None:
        """Build the final context string for the LLM."""
        if not context.retrieved_chunks:
            context.llm_context = ""
            return
            
        parts = []
        for chunk in context.retrieved_chunks:
            parts.append(f"--- File: {chunk.file_path} ---\n{chunk.content}\n")
            
        context.llm_context = "\n".join(parts)
