
"""
RepoLens targeted code retrieval for Deep Search.

Location:
    app/modules/search/pipeline/deep_search_retriever.py

Responsibilities:
    - Request code relevant to verified graph investigation targets.
    - Reuse an adapter for the existing repository-scoped search backend.
    - Enforce target-path checks on returned chunks.
    - Bound target count, chunks per file, and total chunks.
    - Report missing evidence explicitly.

This module does not:
    - Create a Qdrant client.
    - Select or guess a repository collection.
    - Read local files or ZIP archives.
    - Call an LLM.
    - Write to the user's repository.

The injected search adapter must apply the provided collection and path
constraints to the existing search backend. Post-filtering returned chunks
is an additional safeguard, not a substitute for backend filtering.
"""

from __future__ import annotations

import inspect
import logging
import re

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Callable, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)


DEFAULT_MAX_TARGETS = 12
DEFAULT_MAX_CHUNKS_PER_TARGET = 3
DEFAULT_MAX_TOTAL_CHUNKS = 20


# ---------------------------------------------------------------------------
# Public contracts
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TargetedSearchRequest:
    """
    Request sent to the adapter around RepoLens's existing search backend.

    The adapter must search the specified collection and constrain results
    to target_paths. It must not silently fall back to another collection.
    """

    query: str
    repo_name: str
    collection_name: str
    target_paths: tuple[str, ...]
    target_symbols: tuple[str, ...]
    limit: int
    per_target_limit: int


@dataclass(frozen=True)
class TargetedRetrievalResult:
    """Normalized and bounded result returned to the Deep Search workflow."""

    status: str
    retrieved_chunks: tuple[dict[str, Any], ...]
    searched_targets: tuple[str, ...]
    missing_targets: tuple[str, ...]
    retrieved_count: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "retrieved_chunks": list(self.retrieved_chunks),
            "searched_targets": list(self.searched_targets),
            "missing_targets": list(self.missing_targets),
            "retrieved_count": self.retrieved_count,
            "reason": self.reason,
        }


# The adapter accepts one explicit request and returns the existing
# retrieval backend's raw result. It must enforce collection and path scope.
SearchAdapter = Callable[[TargetedSearchRequest], Any]


# ---------------------------------------------------------------------------
# Retriever
# ---------------------------------------------------------------------------

class DeepSearchRetriever:
    """
    Retrieve code for graph-selected investigation targets.

    Expected targets may be:
        - InvestigationTarget objects from deep_search_explorer.py
        - dictionaries containing path/name/kind/node_id
        - repository-relative path strings

    Expected state:
        {
            "repo_name": "owner_repository",
            "collection_name": "repo_owner_repository"
        }

    collection_name must be resolved by RepoLens's existing collection
    selection logic before this retriever is invoked.
    """

    def __init__(
        self,
        *,
        search_adapter: Optional[SearchAdapter] = None,
        max_targets: int = DEFAULT_MAX_TARGETS,
        max_chunks_per_target: int = DEFAULT_MAX_CHUNKS_PER_TARGET,
        max_total_chunks: int = DEFAULT_MAX_TOTAL_CHUNKS,
    ) -> None:
        if max_targets <= 0:
            raise ValueError("max_targets must be positive.")

        if max_chunks_per_target <= 0:
            raise ValueError("max_chunks_per_target must be positive.")

        if max_total_chunks <= 0:
            raise ValueError("max_total_chunks must be positive.")

        self.search_adapter = search_adapter
        self.max_targets = max_targets
        self.max_chunks_per_target = max_chunks_per_target
        self.max_total_chunks = max_total_chunks

    def retrieve(
        self,
        query: str,
        targets: Sequence[Any],
        state: Mapping[str, Any],
    ) -> dict[str, Any]:
        """
        Retrieve bounded code evidence for the supplied targets.

        Returns a dictionary suitable for merging into Deep Search state.
        An unavailable backend or unresolved collection produces an explicit
        UNAVAILABLE result rather than an unscoped search.
        """
        if not isinstance(query, str) or not query.strip():
            return self._result(
                status="UNAVAILABLE",
                reason="The original bug query is empty.",
            )

        if not isinstance(state, Mapping):
            return self._result(
                status="UNAVAILABLE",
                reason="Deep Search state is not a mapping.",
            )

        if self.search_adapter is None:
            logger.error("[DeepSearch] No search adapter configured for DeepSearchRetriever.")
            return self._result(
                status="UNAVAILABLE",
                reason=(
                    "No search adapter is configured. Connect this retriever "
                    "to RepoLens's existing repository-scoped search backend."
                ),
            )

        repo_name = self._read_state_value(state, "repo_name")

        collection_name = (
            self._read_state_value(state, "collection_name")
            or self._read_state_value(state, "resolved_collection")
            or self._read_state_value(state, "selected_collection")
            or self._collection_from_selection(state.get("collection_selection"))
        )

        if not repo_name or not collection_name:
            logger.error(
                f"[DeepSearch] Repository identity or resolved collection is missing "
                f"(repo_name={repo_name!r}, collection={collection_name!r})."
            )
            return self._result(
                status="UNAVAILABLE",
                reason=(
                    "Repository identity or resolved collection is missing. "
                    "Run the existing collection-selection logic before "
                    "targeted retrieval."
                ),
            )

        if not targets:
            return self._result(
                status="INSUFFICIENT_EVIDENCE",
                reason=(
                    "No investigation targets were supplied. The dependency "
                    "explorer must identify targets before code retrieval."
                ),
            )

        normalized_targets = self._normalize_targets(targets)

        if not normalized_targets:
            return self._result(
                status="INSUFFICIENT_EVIDENCE",
                reason=(
                    "No valid repository-relative target paths were supplied."
                ),
            )

        normalized_targets = normalized_targets[: self.max_targets]
        target_paths = tuple(
            dict.fromkeys(target["path"] for target in normalized_targets)
        )
        target_symbols = tuple(
            dict.fromkeys(
                target["name"]
                for target in normalized_targets
                if target.get("name")
            )
        )

        # The query gives the existing hybrid search more context. The
        # adapter must still apply target_paths as a real search constraint.
        target_context = "\n".join(
            f"- {target['path']}"
            + (f" :: {target['name']}" if target.get("name") else "")
            for target in normalized_targets
        )

        scoped_query = (
            f"{query.strip()}\n\n"
            "Deep Search investigation targets:\n"
            f"{target_context}\n\n"
            "Retrieve code that provides evidence for investigating the "
            "reported bug. Prefer exact target files and relevant symbols."
        )

        request = TargetedSearchRequest(
            query=scoped_query,
            repo_name=str(repo_name),
            collection_name=str(collection_name),
            target_paths=target_paths,
            target_symbols=target_symbols,
            limit=min(
                self.max_total_chunks,
                len(target_paths) * self.max_chunks_per_target,
            ),
            per_target_limit=self.max_chunks_per_target,
        )

        try:
            raw_result = self.search_adapter(request)

            if inspect.isawaitable(raw_result):
                raise TypeError(
                    "The search adapter returned an awaitable. This "
                    "retriever expects a synchronous adapter; adapt the "
                    "existing backend to the workflow's execution model."
                )

        except Exception as exc:
            logger.error(
                f"[DeepSearch] Search adapter failed during targeted retrieval for targets {target_paths}: {exc}",
                exc_info=True,
            )
            return self._result(
                status="UNAVAILABLE",
                searched_targets=target_paths,
                reason=(
                    "The existing search backend failed during targeted "
                    f"retrieval ({type(exc).__name__})."
                ),
            )

        raw_chunks = self._extract_chunks(raw_result)

        chunks_by_path: dict[str, list[dict[str, Any]]] = {
            path: [] for path in target_paths
        }
        seen: set[tuple[str, str, Optional[int]]] = set()

        for raw_chunk in raw_chunks:
            normalized = self._normalize_chunk(raw_chunk)

            if normalized is None:
                # Without a verifiable path and source text, the chunk cannot
                # safely be used as evidence for a specific target.
                continue

            path = normalized["path"]

            # Exact path matching prevents unrelated files from being
            # accepted merely because a name or directory partially matches.
            if path not in chunks_by_path:
                continue

            signature = (
                path,
                normalized["content"],
                normalized["line_start"],
            )

            if signature in seen:
                continue

            if len(chunks_by_path[path]) >= self.max_chunks_per_target:
                continue

            seen.add(signature)
            chunks_by_path[path].append(normalized)

            if sum(len(items) for items in chunks_by_path.values()) >= (
                self.max_total_chunks
            ):
                break

        retrieved_chunks: list[dict[str, Any]] = []

        for path in target_paths:
            retrieved_chunks.extend(chunks_by_path[path])

            if len(retrieved_chunks) >= self.max_total_chunks:
                retrieved_chunks = retrieved_chunks[: self.max_total_chunks]
                break

        found_paths = {
            chunk["path"] for chunk in retrieved_chunks
        }
        missing_paths = tuple(
            path for path in target_paths if path not in found_paths
        )

        status = (
            "SUCCESS"
            if retrieved_chunks
            else "INSUFFICIENT_EVIDENCE"
        )

        if retrieved_chunks and missing_paths:
            reason = (
                "Targeted retrieval returned some code evidence, but one or "
                "more investigation files had no matching chunks."
            )
        elif retrieved_chunks:
            reason = (
                "Targeted retrieval returned code chunks whose paths match "
                "the requested investigation targets."
            )
        else:
            reason = (
                "The search backend returned no usable chunks matching the "
                "requested target paths. Evidence is insufficient."
            )

        return TargetedRetrievalResult(
            status=status,
            retrieved_chunks=tuple(retrieved_chunks),
            searched_targets=target_paths,
            missing_targets=missing_paths,
            retrieved_count=len(retrieved_chunks),
            reason=reason,
        ).to_dict()

    # ------------------------------------------------------------------
    # Target normalization
    # ------------------------------------------------------------------

    @classmethod
    def _normalize_targets(
        cls,
        targets: Sequence[Any],
    ) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        seen_paths: set[str] = set()

        for target in targets:
            path = cls._target_value(target, "path")

            if not path and isinstance(target, str):
                path = target

            if not isinstance(path, str):
                continue

            try:
                path = cls._normalize_path(path)
            except ValueError:
                continue

            if path in seen_paths:
                continue

            seen_paths.add(path)

            name = cls._target_value(target, "name")
            kind = cls._target_value(target, "kind")
            node_id = cls._target_value(target, "node_id")

            normalized.append(
                {
                    "path": path,
                    "name": str(name or ""),
                    "kind": str(kind or ""),
                    "node_id": str(node_id or ""),
                }
            )

        return normalized

    @staticmethod
    def _target_value(target: Any, key: str) -> Any:
        if isinstance(target, Mapping):
            return target.get(key)

        return getattr(target, key, None)

    @staticmethod
    def _normalize_path(path: str) -> str:
        raw = path.strip().replace("\\", "/")

        while raw.startswith("./"):
            raw = raw[2:]

        if (
            not raw
            or raw.startswith("/")
            or re.match(r"^[A-Za-z]:", raw)
        ):
            raise ValueError("Expected a repository-relative path.")

        parts = PurePosixPath(raw).parts

        if not parts or any(part in {"..", "."} for part in parts):
            raise ValueError("Unsafe or ambiguous relative path.")

        return "/".join(parts)

    # ------------------------------------------------------------------
    # Existing collection-selection state
    # ------------------------------------------------------------------

    @staticmethod
    def _read_state_value(
        state: Mapping[str, Any],
        key: str,
    ) -> Optional[str]:
        value = state.get(key)

        if isinstance(value, str) and value.strip():
            return value.strip()

        return None

    @classmethod
    def _collection_from_selection(cls, selection: Any) -> Optional[str]:
        if isinstance(selection, str) and selection.strip():
            return selection.strip()

        if isinstance(selection, Mapping):
            for key in (
                "collection_name",
                "resolved_collection",
                "selected_collection",
            ):
                value = selection.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        if selection is not None:
            for key in (
                "collection_name",
                "resolved_collection",
                "selected_collection",
            ):
                value = getattr(selection, key, None)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        return None

    # ------------------------------------------------------------------
    # Result normalization
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_chunks(raw_result: Any) -> list[Any]:
        """
        Accept common result envelopes without assuming a particular
        Qdrant wrapper. The search adapter remains responsible for adapting
        the exact existing backend response.
        """
        if raw_result is None:
            return []

        if isinstance(raw_result, (list, tuple)):
            return list(raw_result)

        if isinstance(raw_result, Mapping):
            for key in (
                "retrieved_chunks",
                "chunks",
                "results",
                "documents",
                "points",
            ):
                value = raw_result.get(key)
                if isinstance(value, (list, tuple)):
                    return list(value)

            # A mapping may itself represent a single chunk.
            if any(
                key in raw_result
                for key in (
                    "code",
                    "content",
                    "text",
                    "page_content",
                    "payload",
                )
            ):
                return [raw_result]

            return []

        for key in (
            "retrieved_chunks",
            "chunks",
            "results",
            "documents",
            "points",
        ):
            value = getattr(raw_result, key, None)
            if isinstance(value, (list, tuple)):
                return list(value)

        return []

    @classmethod
    def _normalize_chunk(
        cls,
        raw_chunk: Any,
    ) -> Optional[dict[str, Any]]:
        root = cls._to_mapping(raw_chunk)
        if not root:
            return None

        payload = cls._to_mapping(root.get("payload"))
        metadata = cls._to_mapping(root.get("metadata"))

        # Some integrations place metadata inside Qdrant's payload;
        # others return a chunk object with its own metadata field.
        nested_metadata = cls._to_mapping(payload.get("metadata"))

        source_maps = (root, payload, metadata, nested_metadata)

        def find_value(*keys: str) -> Any:
            for source in source_maps:
                for key in keys:
                    value = source.get(key)
                    if value is not None and value != "":
                        return value
            return None

        raw_path = find_value(
            "path",
            "file_path",
            "relative_path",
            "source_path",
            "filepath",
            "file_name",
        )

        if not isinstance(raw_path, str):
            return None

        try:
            path = cls._normalize_path(raw_path)
        except ValueError:
            return None

        content = find_value(
            "code",
            "content",
            "text",
            "page_content",
            "chunk_text",
        )

        if not isinstance(content, str) or not content.strip():
            return None

        line_start = find_value(
            "line_start",
            "start_line",
            "start_line_number",
            "line_number",
        )
        line_end = find_value(
            "line_end",
            "end_line",
            "end_line_number",
        )
        score = root.get("score")

        return {
            "path": path,
            "content": content,
            "code": content,
            "score": score,
            "line_start": cls._optional_int(line_start),
            "line_end": cls._optional_int(line_end),
            "metadata": {
                **metadata,
                **nested_metadata,
            },
        }

    @staticmethod
    def _to_mapping(value: Any) -> dict[str, Any]:
        if isinstance(value, Mapping):
            return dict(value)

        if value is None:
            return {}

        # Supports common result objects such as dataclasses and typed
        # retrieval result objects without depending on their class names.
        try:
            values = vars(value)
        except TypeError:
            return {}

        return dict(values) if isinstance(values, Mapping) else {}

    @staticmethod
    def _optional_int(value: Any) -> Optional[int]:
        if isinstance(value, bool):
            return None

        if isinstance(value, int):
            return value

        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return None

        return None

    # ------------------------------------------------------------------
    # Consistent failure responses
    # ------------------------------------------------------------------

    @staticmethod
    def _result(
        *,
        status: str,
        reason: str,
        searched_targets: Sequence[str] = (),
    ) -> dict[str, Any]:
        return TargetedRetrievalResult(
            status=status,
            retrieved_chunks=(),
            searched_targets=tuple(searched_targets),
            missing_targets=(),
            retrieved_count=0,
            reason=reason,
        ).to_dict()


# Alias matching the interface name used by the Deep Search workflow.
TargetedCodeRetriever = DeepSearchRetriever
