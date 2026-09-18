
"""
app/modules/search/pipeline/context_builder.py

Pipeline stage: Context Builder (Step 8).

Responsibilities:

- Build structured code_snippets for downstream validation/analysis.
- Build a compact LLM context.
- Preserve source code exactly as retrieved.
- Use TOON only for structured metadata.
- Avoid duplicate and heavily overlapping chunks.
- Keep the LLM context within a bounded character budget.

Important:

- Source code is NEVER converted into TOON.
- TOON is used only for metadata.
- The exact source code is preserved in code blocks so that
  downstream LLM analysis has reliable code evidence.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.modules.search.domain.search_domain import (
    RetrievedChunk,
    SearchContext,
)
from app.modules.search.pipeline.toon_serializer import (
    build_clean_code_blocks,
    build_toon_llm_context,
)

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Context limits
# ---------------------------------------------------------------------------

# Maximum source-code characters taken from one chunk.
_MAX_CHUNK_CHARS = 1500

# Maximum total characters used for source code + metadata.
_MAX_TOTAL_CHARS = 5000

# Maximum number of chunks passed to the LLM.
_MAX_CONTEXT_CHUNKS = 4

# If this percentage of the smaller chunk overlaps with another chunk,
# treat the smaller chunk as redundant.
_OVERLAP_THRESHOLD = 0.80


class ContextBuilderStage:
    """
    Build the structured and LLM-facing search context.

    Design:

        Retrieved chunks
            ↓
        Remove exact duplicates
            ↓
        Remove heavily overlapping chunks
            ↓
        Primary chunk first
            ↓
        Relevance ordering
            ↓
        Limit number of chunks
            ↓
        Preserve source code
            ↓
        TOON metadata + clean code blocks
            ↓
        context.llm_context
    """

    async def execute(self, context: SearchContext) -> None:
        """
        Build context.code_snippets and context.llm_context.

        Source code is preserved exactly as text, except for the configured
        safety character limit.

        TOON is used only to compact structured metadata.
        """

        # -------------------------------------------------------------------
        # Early exit
        # -------------------------------------------------------------------

        if context.early_exit:
            logger.info(
                "context_builder_skipped",
                reason=context.early_exit,
                repo_id=context.repo_id,
            )
            return

        # -------------------------------------------------------------------
        # No retrieved chunks
        # -------------------------------------------------------------------

        if not context.retrieved_chunks:
            context.code_snippets = []
            context.llm_context = ""

            logger.info(
                "context_builder_no_chunks",
                repo_id=context.repo_id,
            )
            return

        # -------------------------------------------------------------------
        # 1. Order chunks
        # -------------------------------------------------------------------

        ordered_chunks = _order_chunks(context)

        # -------------------------------------------------------------------
        # 2. Remove exact and heavily overlapping chunks
        # -------------------------------------------------------------------

        unique_chunks = _deduplicate_chunks(ordered_chunks)

        # -------------------------------------------------------------------
        # 3. Limit the number of chunks
        # -------------------------------------------------------------------

        selected_chunks = unique_chunks[:_MAX_CONTEXT_CHUNKS]

        snippets: list[dict[str, Any]] = []
        total_source_chars = 0

        # -------------------------------------------------------------------
        # 4. Build structured snippets
        # -------------------------------------------------------------------

        for chunk in selected_chunks:
            is_primary = (
                context.primary_chunk is not None
                and chunk.chunk_hash == context.primary_chunk.chunk_hash
            )

            # Keep source code intact except for the hard safety limit.
            source_code = chunk.content[:_MAX_CHUNK_CHARS]

            # Do not add another chunk if the source-code budget is full.
            if (
                total_source_chars + len(source_code)
                > _MAX_TOTAL_CHARS
            ):
                break

            repo = (
                chunk.metadata.get("repo_name")
                or context.repo_name
            )

            snippet = {
                "repository": repo,
                "file_path": chunk.file_path,
                "function_name": chunk.metadata.get("function_name"),
                "class_name": chunk.metadata.get("class_name"),
                "chunk_type": chunk.metadata.get("chunk_type"),
                "start_line": chunk.metadata.get("start_line"),
                "end_line": chunk.metadata.get("end_line"),
                "source_code": source_code,
                "score": round(chunk.score, 4),
                "is_primary": is_primary,
                "chunk_hash": chunk.chunk_hash,
                "language": chunk.metadata.get("language"),
            }

            snippets.append(snippet)
            total_source_chars += len(source_code)

        # -------------------------------------------------------------------
        # Store structured snippets
        # -------------------------------------------------------------------

        context.code_snippets = snippets

        # -------------------------------------------------------------------
        # No snippets survived the limits
        # -------------------------------------------------------------------

        if not snippets:
            context.llm_context = ""

            logger.info(
                "context_builder_empty_after_limits",
                repo_id=context.repo_id,
                retrieved_chunks=len(context.retrieved_chunks),
            )
            return

        # -------------------------------------------------------------------
        # 5. Build clean source-code blocks
        #
        # The source code is intentionally NOT TOON encoded.
        # -------------------------------------------------------------------

        clean_blocks = build_clean_code_blocks(snippets)

        # -------------------------------------------------------------------
        # 6. Build TOON metadata + source code context
        # -------------------------------------------------------------------

        try:
            toon_context = build_toon_llm_context(
                snippets=snippets,
                code_blocks=clean_blocks,
            )

            # Final safety limit.
            if len(toon_context) > _MAX_TOTAL_CHARS:
                toon_context = _truncate_context(
                    toon_context,
                    _MAX_TOTAL_CHARS,
                )

            context.llm_context = toon_context

        except Exception as exc:
            logger.warning(
                "toon_serialization_failed",
                error=str(exc),
                repo_id=context.repo_id,
                chunk_count=len(snippets),
            )

            # Safe fallback:
            # preserve the original clean code blocks without TOON.
            fallback_context = "\n\n".join(clean_blocks)

            context.llm_context = _truncate_context(
                fallback_context,
                _MAX_TOTAL_CHARS,
            )

        # -------------------------------------------------------------------
        # 7. Logging
        # -------------------------------------------------------------------

        logger.info(
            "context_built",
            repo_id=context.repo_id,
            retrieved_chunks=len(context.retrieved_chunks),
            unique_chunks=len(unique_chunks),
            selected_chunks=len(snippets),
            source_code_chars=total_source_chars,
            llm_context_chars=len(context.llm_context),
            target_symbol=context.target_symbol,
            primary_chunk=(
                context.primary_chunk.file_path
                if context.primary_chunk is not None
                else None
            ),
        )

        print(
            f"FINAL CONTEXT CHUNKS: {len(context.code_snippets)}"
        )


# ---------------------------------------------------------------------------
# Chunk ordering
# ---------------------------------------------------------------------------


def _order_chunks(
    context: SearchContext,
) -> list[RetrievedChunk]:
    """
    Order chunks for downstream analysis.

    Priority:

        1. Primary chunk
        2. Remaining chunks by descending score
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


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def _deduplicate_chunks(
    chunks: list[RetrievedChunk],
) -> list[RetrievedChunk]:
    """
    Remove exact duplicate and heavily overlapping chunks.

    Two levels of deduplication are performed:

    1. Exact duplicate detection using chunk_hash.
    2. Line-range overlap detection for chunks from the same file.

    When two chunks overlap heavily, the larger chunk is retained because
    it provides more complete code context to the downstream LLM.

    Example:

        app.py 13-49
        app.py 13-52

    Result:

        app.py 13-52

    Different or only slightly overlapping chunks are preserved.
    """

    # -----------------------------------------------------------------------
    # 1. Remove exact duplicates using chunk_hash
    # -----------------------------------------------------------------------

    seen_hashes: set[str] = set()
    exact_unique: list[RetrievedChunk] = []

    for chunk in chunks:
        chunk_hash = getattr(chunk, "chunk_hash", None)

        if chunk_hash:
            key = str(chunk_hash)
        else:
            # Fallback when chunk_hash is unavailable.
            key = (
                f"{chunk.file_path}:"
                f"{chunk.metadata.get('start_line')}:"
                f"{chunk.metadata.get('end_line')}:"
                f"{chunk.content}"
            )

        if key in seen_hashes:
            continue

        seen_hashes.add(key)
        exact_unique.append(chunk)

    # -----------------------------------------------------------------------
    # 2. Remove heavily overlapping chunks
    # -----------------------------------------------------------------------

    unique: list[RetrievedChunk] = []

    for chunk in exact_unique:
        current_start = _get_line_number(
            chunk,
            "start_line",
        )
        current_end = _get_line_number(
            chunk,
            "end_line",
        )

        # If line information is unavailable, we cannot safely compare
        # overlap. Keep the chunk.
        if current_start is None or current_end is None:
            unique.append(chunk)
            continue

        chunk_redundant = False

        for index, existing in enumerate(unique):

            # Only compare chunks from the same file.
            if existing.file_path != chunk.file_path:
                continue

            existing_start = _get_line_number(
                existing,
                "start_line",
            )
            existing_end = _get_line_number(
                existing,
                "end_line",
            )

            # If either chunk has no valid line range, skip overlap detection.
            if existing_start is None or existing_end is None:
                continue

            # Check whether the line ranges overlap.
            if not _line_overlap(
                current_start,
                current_end,
                existing_start,
                existing_end,
            ):
                continue

            # ---------------------------------------------------------------
            # Calculate overlap
            # ---------------------------------------------------------------

            overlap_start = max(
                current_start,
                existing_start,
            )

            overlap_end = min(
                current_end,
                existing_end,
            )

            overlap_size = (
                overlap_end - overlap_start + 1
            )

            current_size = (
                current_end - current_start + 1
            )

            existing_size = (
                existing_end - existing_start + 1
            )

            smaller_size = min(
                current_size,
                existing_size,
            )

            if smaller_size <= 0:
                continue

            overlap_ratio = (
                overlap_size / smaller_size
            )

            # ---------------------------------------------------------------
            # If >= 80% of the smaller chunk is covered by the
            # larger chunk, treat the smaller one as redundant.
            # ---------------------------------------------------------------

            if overlap_ratio >= _OVERLAP_THRESHOLD:

                if current_size > existing_size:
                    # Current chunk contains more lines, so replace
                    # the existing smaller chunk.
                    unique[index] = chunk

                # Either:
                #
                # current is smaller
                # OR
                # current replaced existing
                #
                # In both cases we do not add current again.
                chunk_redundant = True
                break

        if not chunk_redundant:
            unique.append(chunk)

    return unique


# ---------------------------------------------------------------------------
# Line helpers
# ---------------------------------------------------------------------------


def _get_line_number(
    chunk: RetrievedChunk,
    field: str,
) -> int | None:
    """
    Safely extract a line number from chunk metadata.

    Returns None when the value is missing or cannot be converted
    to an integer.
    """

    value = chunk.metadata.get(field)

    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _line_overlap(
    start_a: int,
    end_a: int,
    start_b: int,
    end_b: int,
) -> bool:
    """
    Return True when two line ranges overlap.

    Example:

        13-49 and 13-52 -> True
        13-49 and 50-80 -> False
    """

    return max(
        start_a,
        start_b,
    ) <= min(
        end_a,
        end_b,
    )


# ---------------------------------------------------------------------------
# Context truncation
# ---------------------------------------------------------------------------
def _truncate_context(
    text: str,
    max_chars: int,
) -> str:
    """
    Safely truncate the final LLM context.

    This is a final safety mechanism only.

    Ideally the context should already be below the limit because
    chunks were selected before serialization.
    """

    if len(text) <= max_chars:
        return text

    truncated = text[:max_chars]

    return (
        truncated
        + "\n\n"
        + "[Context truncated because the LLM context budget was reached.]"
    )

