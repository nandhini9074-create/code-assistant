
"""
app/modules/search/pipeline/context_builder.py

Pipeline stage: Context Builder (Step 8).

Builds:
- context.code_snippets: structured representations of retrieved chunks.
- context.llm_context: bounded text context for downstream LLM analysis.

The primary chunk is placed first when available, followed by the
remaining retrieved chunks ordered by relevance score.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.modules.search.domain.search_domain import (
    RetrievedChunk,
    SearchContext,
)

logger = get_logger(__name__)


# Maximum characters included from an individual chunk.
_MAX_CHUNK_CHARS = 2000

# Maximum total characters included in the LLM context.
_MAX_TOTAL_CHARS = 8000


class ContextBuilderStage:
    """Pipeline stage responsible for building structured LLM context."""

    async def execute(self, context: SearchContext) -> None:
        """
        Build structured snippets and the formatted LLM context.

        The primary chunk is placed first, followed by remaining
        retrieved chunks ordered by descending relevance score.

        Both code_snippets and llm_context contain the same set of
        chunks so downstream stages operate on consistent evidence.
        """

        if context.early_exit:
            logger.info(
                "context_builder_skipped",
                reason=context.early_exit,
                repo_id=context.repo_id,
            )
            return

        if not context.retrieved_chunks:
            context.code_snippets = []
            context.llm_context = ""

            logger.info(
                "context_builder_no_chunks",
                repo_id=context.repo_id,
            )
            return

        ordered_chunks = _order_chunks(context)

        snippets: list[dict[str, Any]] = []
        parts: list[str] = []
        total_chars = 0

        for chunk in ordered_chunks:
            # Limit the amount of content taken from an individual chunk.
            truncated_content = chunk.content[:_MAX_CHUNK_CHARS]

            is_primary = (
                context.primary_chunk is not None
                and chunk.chunk_hash == context.primary_chunk.chunk_hash
            )

            repo = chunk.metadata.get("repo_name") or context.repo_name
            start_line = chunk.metadata.get("start_line")
            end_line = chunk.metadata.get("end_line")
            func_name = chunk.metadata.get("function_name")
            class_name = chunk.metadata.get("class_name")
            chunk_type = chunk.metadata.get("chunk_type")

            snippet = {
                "repository": repo,
                "file_path": chunk.file_path,
                "function_name": func_name,
                "class_name": class_name,
                "chunk_type": chunk_type,
                "start_line": start_line,
                "end_line": end_line,
                "source_code": truncated_content,
                "score": round(chunk.score, 4),
                "is_primary": is_primary,
                "chunk_hash": chunk.chunk_hash,
                "language": chunk.metadata.get("language"),
            }

            # ---------------------------------------------------------
            # Build the LLM context block
            # ---------------------------------------------------------
            primary_marker = "[PRIMARY] " if is_primary else ""

            details = []
            if repo:
                details.append(f"Repository: {repo}")
            details.append(f"File: {chunk.file_path}")
            if class_name:
                details.append(f"Class: {class_name}")
            if func_name:
                details.append(f"Function: {func_name}")
            if chunk_type:
                details.append(f"Chunk Type: {chunk_type}")
            if start_line is not None and end_line is not None:
                details.append(f"Lines: {start_line}–{end_line}")

            header = f"--- {primary_marker}" + " | ".join(details) + f" | score={snippet['score']} ---"

            block = (
                f"{header}\n"
                f"{truncated_content}\n"
            )

            block_chars = len(block)

            # Do not add a snippet unless its corresponding block
            # actually fits inside the LLM context budget.
            if total_chars + block_chars > _MAX_TOTAL_CHARS:
                break

            snippets.append(snippet)
            parts.append(block)
            total_chars += block_chars

        context.code_snippets = snippets
        context.llm_context = "\n".join(parts)

        print(f"FINAL CONTEXT CHUNKS: {len(context.code_snippets)}")

        logger.info(
            "context_built",
            repo_id=context.repo_id,
            snippets=len(context.code_snippets),
            llm_context_chars=len(context.llm_context),
            target_symbol=context.target_symbol,
            primary_chunk=(
                context.primary_chunk.file_path
                if context.primary_chunk is not None
                else None
            ),
        )


def _order_chunks(
    context: SearchContext,
) -> list[RetrievedChunk]:
    """
    Return chunks ordered for downstream analysis.

    Ordering:
    1. Primary chunk, when available.
    2. Remaining chunks by descending retrieval score.
    """

    primary = context.primary_chunk

    if primary is None:
        return sorted(
            context.retrieved_chunks,
            key=lambda chunk: chunk.score,
            reverse=True,
        )

    rest = [
        chunk
        for chunk in context.retrieved_chunks
        if chunk.chunk_hash != primary.chunk_hash
    ]

    rest.sort(
        key=lambda chunk: chunk.score,
        reverse=True,
    )

    return [primary, *rest]
