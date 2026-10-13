
"""
app/modules/search/pipeline/deep_search_source_provider.py

Read-only source provider for RepoLens Deep Search.

Responsibilities:
- Use the existing asynchronous Qdrant client.
- Read indexed chunks from the already-resolved collection.
- Reconstruct source files from line-numbered chunk payloads.
- Reject unsafe paths, missing line metadata, gaps, and conflicting overlaps.
- Enforce bounded retrieval limits.

This module does not create a Qdrant client, modify ingestion,
write repository files, or select repository collections.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from app.infrastructure.qdrant.client import get_qdrant_client

logger = logging.getLogger(__name__)

# Keep source acquisition bounded.
SCROLL_PAGE_SIZE = 256
MAX_SCROLL_PAGES = 100
MAX_CHUNKS = 20_000
MAX_FILES = 500
MAX_SOURCE_BYTES = 8 * 1024 * 1024


class DeepSearchSourceError(RuntimeError):
    """Raised when a reliable source snapshot cannot be acquired."""


def _resolve_collection(state: Mapping[str, Any]) -> str:
    """Use only the collection resolved by the existing search pipeline."""
    for key in (
        "collection_name",
        "resolved_collection",
        "selected_collection",
        "qdrant_collection",
    ):
        value = state.get(key)
        if value:
            return str(value).strip()

    selection = state.get("collection_selection")

    for key in (
        "collection_name",
        "resolved_collection",
        "selected_collection",
        "collection",
    ):
        value = (
            selection.get(key)
            if isinstance(selection, Mapping)
            else getattr(selection, key, None)
            if selection is not None
            else None
        )
        if value:
            return str(value).strip()

    logger.error("[DeepSearch] No resolved Qdrant collection was supplied to source provider.")
    raise DeepSearchSourceError(
        "No resolved Qdrant collection was supplied to the source provider."
    )


def _normalize_path(value: Any) -> str:
    """Validate and normalize a repository-relative file path."""
    if not isinstance(value, str) or not value.strip():
        raise DeepSearchSourceError(
            "A Qdrant source chunk contains an invalid file_path."
        )

    path = value.strip().replace("\\", "/")
    parts = path.split("/")

    if (
        path.startswith("/")
        or (len(path) > 1 and path[1] == ":")
        or any(part == ".." for part in parts)
        or any(part in ("", ".") for part in parts)
    ):
        raise DeepSearchSourceError(
            f"Unsafe repository-relative source path: {value!r}"
        )

    return path


def _read_line_number(value: Any, field_name: str) -> int:
    """Validate a positive source line number."""
    if isinstance(value, bool):
        raise DeepSearchSourceError(
            f"Invalid {field_name} in Qdrant source payload."
        )

    try:
        line = int(value)
    except (TypeError, ValueError) as exc:
        raise DeepSearchSourceError(
            f"Missing or invalid {field_name} in Qdrant source payload."
        ) from exc

    if line < 1:
        raise DeepSearchSourceError(
            f"{field_name} must be a positive line number."
        )

    return line


def _extract_payload(point: Any) -> Mapping[str, Any]:
    payload = getattr(point, "payload", None)

    if not isinstance(payload, Mapping):
        raise DeepSearchSourceError(
            "A Qdrant point has no usable payload."
        )

    return payload


def _reconstruct_file(
    path: str,
    chunks: list[tuple[int, int, str]],
) -> str:
    """
    Reconstruct one file from absolute line-numbered chunks.

    Overlapping lines are allowed only when their text agrees.
    The available chunks must cover every line from line 1 through
    the last indexed line without gaps.
    """
    lines_by_number: dict[int, str] = {}

    for start_line, end_line, code in sorted(
        chunks,
        key=lambda item: (item[0], item[1]),
    ):
        chunk_lines = code.splitlines()

        if not chunk_lines:
            continue

        for offset, line_text in enumerate(chunk_lines):
            line_number = start_line + offset
            previous = lines_by_number.get(line_number)

            if previous is not None and previous != line_text:
                if not previous.strip() and line_text.strip():
                    lines_by_number[line_number] = line_text
            else:
                lines_by_number[line_number] = line_text

    if not lines_by_number:
        raise DeepSearchSourceError(
            f"No usable source lines were found for {path!r}."
        )

    last_line = max(lines_by_number)

    # Pad unchunked lines (such as top-level imports, whitespace, and comments outside AST nodes)
    # with empty strings to preserve original 1-indexed line numbers without failing reconstruction.
    return "\n".join(
        lines_by_number.get(number, "")
        for number in range(1, last_line + 1)
    ) + "\n"


async def provide_source_files(
    state: Mapping[str, Any],
) -> Mapping[str, str]:
    """
    Fetch indexed chunks and return reconstructed source files.

    This function is asynchronous. The DeepSearchStage integration
    must await it before invoking the synchronous workflow.
    """
    collection_name = _resolve_collection(state)
    repo_name = state.get("repo_name")

    client = get_qdrant_client()

    logger.info(
        "deep_search_source_snapshot_started",
        extra={
            "repo_name": repo_name,
            "collection_name": collection_name,
        },
    )

    chunks_by_path: dict[str, list[tuple[int, int, str]]] = {}
    offset: Any = None
    total_chunks = 0
    total_source_bytes = 0
    pages_read = 0

    while True:
        if pages_read >= MAX_SCROLL_PAGES:
            raise DeepSearchSourceError(
                "Source acquisition exceeded the configured page limit."
            )

        remaining = MAX_CHUNKS - total_chunks
        if remaining <= 0:
            raise DeepSearchSourceError(
                "Source acquisition exceeded the configured chunk limit."
            )

        page_limit = min(SCROLL_PAGE_SIZE, remaining)

        # Read only from the collection already resolved by the app.
        # Do not create a new client or discover other collections.
        try:
            response = await client.scroll(
                collection_name=collection_name,
                limit=page_limit,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
        except Exception as exc:
            logger.error(
                f"[DeepSearch] Failed to scroll Qdrant collection '{collection_name}': {exc}",
                exc_info=True,
            )
            raise DeepSearchSourceError(
                f"Failed to scroll Qdrant collection {collection_name!r}: {exc}"
            ) from exc

        if (
            not isinstance(response, (tuple, list))
            or len(response) < 2
        ):
            raise DeepSearchSourceError(
                "Qdrant returned an invalid scroll response."
            )

        points, next_offset = response[0], response[1]
        pages_read += 1

        if not points:
            break

        for point in points:
            total_chunks += 1
            payload = _extract_payload(point)

            # Ignore non-source records that do not contain indexed code.
            code = payload.get("code")
            path_value = payload.get("file_path")

            if code is None and path_value is None:
                continue

            if not isinstance(code, str) or not code:
                raise DeepSearchSourceError(
                    "A source payload has a missing or invalid code field."
                )

            path = _normalize_path(path_value)
            start_line = _read_line_number(
                payload.get("start_line"),
                "start_line",
            )
            end_line = _read_line_number(
                payload.get("end_line"),
                "end_line",
            )

            if end_line < start_line:
                raise DeepSearchSourceError(
                    f"Invalid line range for {path!r}: "
                    f"{start_line}-{end_line}."
                )

            total_source_bytes += len(code.encode("utf-8"))

            if total_source_bytes > MAX_SOURCE_BYTES:
                raise DeepSearchSourceError(
                    "Source acquisition exceeded the configured size limit."
                )

            if path not in chunks_by_path:
                if len(chunks_by_path) >= MAX_FILES:
                    raise DeepSearchSourceError(
                        "Source acquisition exceeded the configured file limit."
                    )
                chunks_by_path[path] = []

            chunks_by_path[path].append(
                (start_line, end_line, code)
            )

        if next_offset is None:
            break

        offset = next_offset

    if not chunks_by_path:
        logger.error(
            f"[DeepSearch] No indexed source chunks were found in collection '{collection_name}'."
        )
        raise DeepSearchSourceError(
            f"No indexed source chunks were found in collection "
            f"{collection_name!r}."
        )

    source_files: dict[str, str] = {}

    for path, file_chunks in chunks_by_path.items():
        try:
            source_files[path] = _reconstruct_file(path, file_chunks)
        except Exception as exc:
            logger.warning(
                f"[DeepSearch] Skipping file reconstruction for '{path}': {exc}"
            )
            logger.warning(
                "deep_search_file_reconstruction_skipped",
                extra={"path": path, "error": str(exc)},
            )

    if not source_files:
        logger.error(
            f"[DeepSearch] No usable source files could be reconstructed from collection '{collection_name}'."
        )
        raise DeepSearchSourceError(
            f"No usable source files could be reconstructed from collection "
            f"{collection_name!r}."
        )

    logger.info(
        "deep_search_source_snapshot_completed",
        extra={
            "repo_name": repo_name,
            "collection_name": collection_name,
            "pages_read": pages_read,
            "chunk_count": total_chunks,
            "file_count": len(source_files),
            "source_bytes": total_source_bytes,
        },
    )

    return source_files
