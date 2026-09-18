
"""
app/modules/search/pipeline/toon_serializer.py

TOON serialization utility.

TOON is used only for compact structured metadata.

IMPORTANT:
- Source code is NEVER transformed into TOON.
- Source code is preserved exactly as retrieved.
- Retrieval scores are kept in application-side snippets but are not
  sent to the LLM because they provide little semantic value.
- Internal retrieval/ranking metadata such as is_primary is NOT sent
  to the LLM.
- The LLM receives:
      1. compact TOON metadata
      2. original source-code blocks
"""

from __future__ import annotations

from typing import Any

import toons


class ToonSerializationError(Exception):
    """Raised when TOON serialization fails."""


def serialize_snippets_to_toon(
    snippets: list[dict[str, Any]],
) -> str:
    """
    Serialize snippet metadata into compact TOON format.

    The following fields may be sent to the LLM:

        file
        lines
        function
        class
        type
        repo

    Retrieval score and internal ranking metadata such as is_primary
    are intentionally excluded from the LLM context.

    Source code is also excluded because it is preserved separately.
    """

    if not snippets:
        return ""

    has_repo = any(
        bool(snippet.get("repository"))
        for snippet in snippets
    )

    has_function = any(
        bool(snippet.get("function_name"))
        for snippet in snippets
    )

    has_class = any(
        bool(snippet.get("class_name"))
        for snippet in snippets
    )

    has_type = any(
        bool(snippet.get("chunk_type"))
        for snippet in snippets
    )

    rows: list[dict[str, Any]] = []

    for snippet in snippets:
        start_line = snippet.get("start_line")
        end_line = snippet.get("end_line")

        if (
            start_line is not None
            and end_line is not None
        ):
            lines = f"{start_line}-{end_line}"
        else:
            lines = "?"

        # NOTE:
        # Internal fields such as is_primary are intentionally NOT
        # serialized because they represent retrieval/ranking information,
        # not confirmed target identity.
        row: dict[str, Any] = {
            "file": (
                snippet.get("file_path")
                or "unknown"
            ),
            "lines": lines,
        }

        if has_function:
            row["function"] = (
                snippet.get("function_name")
                or ""
            )

        if has_class:
            row["class"] = (
                snippet.get("class_name")
                or ""
            )

        if has_type:
            row["type"] = (
                snippet.get("chunk_type")
                or ""
            )

        if has_repo:
            row["repo"] = (
                snippet.get("repository")
                or ""
            )

        rows.append(row)

    try:
        return toons.dumps(rows)

    except Exception as exc:
        raise ToonSerializationError(
            f"TOON serialization failed: {exc}"
        ) from exc


def build_clean_code_blocks(
    snippets: list[dict[str, Any]],
) -> list[str]:
    """
    Build source-code blocks corresponding to TOON rows.

    The source code itself is NOT modified or serialized.

    Example:

        [1]
        async def appeal(...):
            ...

        [2]
        def process(...):
            ...
    """

    blocks: list[str] = []

    for index, snippet in enumerate(
        snippets,
        start=1,
    ):
        source = snippet.get(
            "source_code",
            "",
        )

        if not source:
            continue

        blocks.append(
            f"[{index}]\n{source}"
        )

    return blocks


def build_toon_llm_context(
    snippets: list[dict[str, Any]],
    code_blocks: list[str] | None = None,
) -> str:
    """
    Build the final LLM context.

    Structure:

        TOON metadata

        [1]
        source code

        [2]
        source code

    The metadata and code are kept separate so that the
    source code remains unchanged.
    """

    if not snippets:
        return ""

    toon_table = serialize_snippets_to_toon(
        snippets
    )

    if code_blocks is None:
        clean_blocks = build_clean_code_blocks(
            snippets
        )
    else:
        clean_blocks = code_blocks

    if not clean_blocks:
        return toon_table

    if not toon_table:
        return "\n\n".join(clean_blocks)

    return (
        f"{toon_table}\n\n"
        + "\n\n".join(clean_blocks)
    )
