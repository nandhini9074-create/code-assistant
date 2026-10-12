
"""
RepoLens Deep Search evidence assessor.

Location:
    app/modules/search/pipeline/deep_search_assessor.py

Responsibilities:
    - Assess retrieved code evidence using an injected analysis adapter.
    - Validate evidence quotations against actual retrieved code.
    - Reject unsupported or unverified diagnoses.
    - Select verified graph nodes for bounded follow-up investigation.
    - Return structured outcomes for the Deep Search workflow.

This module does not:
    - Create an LLM client or assume an LLM API signature.
    - Retrieve code from Qdrant.
    - Generate code patches.
    - Modify repository files.
    - Treat lexical similarity as proof of a bug.
"""

from __future__ import annotations

import inspect
import re

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Callable, Mapping, Optional, Sequence


DEFAULT_MAX_FOLLOW_UP_TARGETS = 8
DEFAULT_MAX_ROUNDS = 3
DEFAULT_MIN_CONFIDENCE = 0.55


# ---------------------------------------------------------------------------
# Public result models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VerifiedEvidence:
    """A claim supported by an exact quotation from retrieved source."""

    path: str
    quote: str
    claim: str
    line_start: Optional[int] = None
    line_end: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "quote": self.quote,
            "claim": self.claim,
            "line_start": self.line_start,
            "line_end": self.line_end,
        }


@dataclass(frozen=True)
class AssessmentResult:
    """
    Structured outcome consumed by the Deep Search workflow.

    Status values:
        complete:
            A diagnosis is supported by verified retrieved evidence.
        running:
            More investigation is needed and verified follow-up targets exist.
        incomplete:
            Evidence is insufficient to diagnose the bug safely.
        unavailable:
            Assessment could not be performed reliably.
    """

    status: str
    diagnosis: Optional[str]
    confidence: float
    evidence: tuple[VerifiedEvidence, ...]
    follow_up_targets: tuple[str, ...]
    follow_up_query: Optional[str]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "diagnosis": self.diagnosis,
            "confidence": self.confidence,
            "evidence": [
                item.to_dict() for item in self.evidence
            ],
            "follow_up_targets": list(self.follow_up_targets),
            "follow_up_query": self.follow_up_query,
            "reason": self.reason,
        }


# The adapter must be implemented using the application's actual analysis
# service. It receives a JSON-compatible evidence payload and returns a
# mapping following the contract documented below.
AssessmentAdapter = Callable[[Mapping[str, Any]], Mapping[str, Any]]


class DeepSearchAssessor:
    """
    Assess whether retrieved code is sufficient to explain a reported bug.

    Adapter input:
        {
            "query": "...",
            "targets": [...],
            "retrieved_chunks": [
                {
                    "path": "...",
                    "content": "...",
                    "line_start": 10,
                    "line_end": 20
                }
            ],
            "unresolved_references": [...],
            "rounds": 1,
            "max_rounds": 3
        }

    Adapter output:
        {
            "is_sufficient": True,
            "diagnosis": "...",
            "confidence": 0.8,
            "evidence": [
                {
                    "path": "app/example.py",
                    "quote": "exact text copied from retrieved code",
                    "claim": "What this source proves",
                    "line_start": 10,
                    "line_end": 10
                }
            ],
            "follow_up_targets": [],
            "follow_up_query": None,
            "reason": "..."
        }

    Follow-up targets may be existing graph node IDs, repository-relative
    paths, or dictionaries containing a path and optional symbol name.
    Returned targets are validated against the dependency graph.

    Without an adapter, the assessor does not pretend that deterministic
    checks alone can establish a root cause.
    """

    def __init__(
        self,
        *,
        assessment_adapter: Optional[AssessmentAdapter] = None,
        max_follow_up_targets: int = DEFAULT_MAX_FOLLOW_UP_TARGETS,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    ) -> None:
        if max_follow_up_targets <= 0:
            raise ValueError(
                "max_follow_up_targets must be positive."
            )

        if max_rounds <= 0:
            raise ValueError("max_rounds must be positive.")

        if not 0.0 <= min_confidence <= 1.0:
            raise ValueError(
                "min_confidence must be between 0 and 1."
            )

        self.assessment_adapter = assessment_adapter
        self.max_follow_up_targets = max_follow_up_targets
        self.max_rounds = max_rounds
        self.min_confidence = min_confidence

    def assess(
        self,
        state: Mapping[str, Any],
    ) -> dict[str, Any]:
        """
        Assess current Deep Search state.

        This method is synchronous to match a synchronous LangGraph node.
        Adapt the caller and adapter together if the existing workflow uses
        asynchronous nodes.
        """
        if not isinstance(state, Mapping):
            return self._unavailable(
                "The Deep Search state is not a mapping."
            )

        query = state.get("query")

        if not isinstance(query, str) or not query.strip():
            return self._unavailable(
                "The original bug query is missing."
            )

        chunks = self._normalize_chunks(
            state.get("retrieved_chunks", [])
        )

        if not chunks:
            return self._incomplete(
                reason=(
                    "No usable source chunks were retrieved. A diagnosis "
                    "cannot be established without source evidence."
                )
            )

        if self.assessment_adapter is None:
            return self._incomplete(
                reason=(
                    "No assessment adapter is configured. Retrieved code "
                    "is available, but root-cause assessment cannot be "
                    "claimed as completed."
                )
            )

        rounds = self._read_nonnegative_int(
            state.get("rounds"),
            default=0,
        )

        max_rounds = self._read_positive_int(
            state.get("max_rounds"),
            default=self.max_rounds,
        )

        payload = {
            "query": query.strip(),
            "intent": str(state.get("intent", "FIX_BUG")),
            "targets": self._json_safe(state.get("targets", [])),
            "retrieved_chunks": chunks,
            "unresolved_references": self._json_safe(
                state.get("unresolved_references", [])
            ),
            "rounds": rounds,
            "max_rounds": max_rounds,
            "instructions": (
                "Diagnose only what the supplied source supports. "
                "Do not invent files, functions, fields, runtime behavior, "
                "or test results. Every evidence item must cite an exact "
                "quotation from a retrieved chunk. If more source is needed, "
                "propose only existing dependency-graph targets."
            ),
        }

        try:
            raw_assessment = self.assessment_adapter(payload)

            if inspect.isawaitable(raw_assessment):
                # Avoid silently proceeding with an unawaited assessment.
                close = getattr(raw_assessment, "close", None)
                if callable(close):
                    close()

                return self._unavailable(
                    "The assessment adapter returned an awaitable, but this "
                    "assessor is configured for synchronous execution."
                )

        except Exception as exc:
            return self._unavailable(
                "The assessment adapter failed "
                f"({type(exc).__name__})."
            )

        if not isinstance(raw_assessment, Mapping):
            return self._unavailable(
                "The assessment adapter returned an invalid result."
            )

        return self._validate_assessment(
            raw_assessment=raw_assessment,
            state=state,
            chunks=chunks,
            rounds=rounds,
            max_rounds=max_rounds,
        )

    # ------------------------------------------------------------------
    # Validate assessment and citations
    # ------------------------------------------------------------------

    def _validate_assessment(
        self,
        *,
        raw_assessment: Mapping[str, Any],
        state: Mapping[str, Any],
        chunks: list[dict[str, Any]],
        rounds: int,
        max_rounds: int,
    ) -> dict[str, Any]:
        verified_evidence = self._verify_evidence(
            raw_assessment.get("evidence", []),
            chunks,
        )

        confidence = self._read_confidence(
            raw_assessment.get("confidence")
        )

        diagnosis = raw_assessment.get("diagnosis")
        if not isinstance(diagnosis, str) or not diagnosis.strip():
            diagnosis = None
        else:
            diagnosis = diagnosis.strip()

        # A claimed sufficient diagnosis must have a meaningful explanation,
        # verified source evidence, and enough confidence.
        requested_sufficient = (
            raw_assessment.get("is_sufficient") is True
        )

        sufficient = (
            requested_sufficient
            and diagnosis is not None
            and bool(verified_evidence)
            and confidence >= self.min_confidence
        )

        reason_value = raw_assessment.get("reason")
        reason = (
            reason_value.strip()
            if isinstance(reason_value, str) and reason_value.strip()
            else "Assessment completed; evidence was checked against source."
        )

        if sufficient:
            return AssessmentResult(
                status="complete",
                diagnosis=diagnosis,
                confidence=confidence,
                evidence=tuple(verified_evidence),
                follow_up_targets=(),
                follow_up_query=None,
                reason=reason,
            ).to_dict()

        # An insufficient diagnosis must not leak into the final result as
        # though it were established. Keep only evidence that was verified.
        graph = state.get("dependency_graph")

        follow_up_targets = self._resolve_follow_up_targets(
            raw_targets=raw_assessment.get("follow_up_targets", []),
            graph=graph,
        )

        follow_up_query = raw_assessment.get("follow_up_query")
        if not isinstance(follow_up_query, str):
            follow_up_query = None

        follow_up_query = (
            follow_up_query.strip()
            if follow_up_query and follow_up_query.strip()
            else None
        )

        can_continue = (
            rounds + 1 < max_rounds
            and bool(follow_up_targets)
        )

        if can_continue:
            return AssessmentResult(
                status="running",
                diagnosis=None,
                confidence=confidence,
                evidence=tuple(verified_evidence),
                follow_up_targets=tuple(follow_up_targets),
                follow_up_query=(
                    follow_up_query
                    or (
                        "Investigate the verified dependency targets to "
                        "find additional evidence for the original bug."
                    )
                ),
                reason=(
                    reason
                    + " The available evidence is not yet sufficient; "
                    "bounded follow-up investigation is available."
                ),
            ).to_dict()

        return AssessmentResult(
            status="incomplete",
            diagnosis=None,
            confidence=confidence,
            evidence=tuple(verified_evidence),
            follow_up_targets=(),
            follow_up_query=None,
            reason=(
                reason
                + " A verified diagnosis could not be established within "
                "the available evidence and investigation limits."
            ),
        ).to_dict()

    @classmethod
    def _verify_evidence(
        cls,
        raw_evidence: Any,
        chunks: Sequence[Mapping[str, Any]],
    ) -> list[VerifiedEvidence]:
        """
        Accept only source quotations found in retrieved chunks.

        A path alone is not sufficient evidence. The quoted text must match
        retrieved content after whitespace normalization.
        """
        if not isinstance(raw_evidence, (list, tuple)):
            return []

        chunks_by_path: dict[str, list[Mapping[str, Any]]] = {}

        for chunk in chunks:
            chunks_by_path.setdefault(
                str(chunk["path"]), []
            ).append(chunk)

        verified: list[VerifiedEvidence] = []
        seen: set[tuple[str, str, str]] = set()

        for item in raw_evidence:
            if not isinstance(item, Mapping):
                continue

            raw_path = item.get("path")
            raw_quote = item.get("quote")
            raw_claim = item.get("claim")

            if not isinstance(raw_path, str):
                continue

            try:
                path = cls._normalize_path(raw_path)
            except ValueError:
                continue

            if not isinstance(raw_quote, str) or not raw_quote.strip():
                continue

            if not isinstance(raw_claim, str) or not raw_claim.strip():
                continue

            quote = raw_quote.strip()
            claim = raw_claim.strip()

            candidate_chunks = chunks_by_path.get(path, [])
            matching_chunk = next(
                (
                    chunk
                    for chunk in candidate_chunks
                    if cls._contains_exact_quote(
                        str(chunk["content"]),
                        quote,
                    )
                ),
                None,
            )

            if matching_chunk is None:
                # Do not trust a quotation that cannot be located in the
                # actual retrieved code for the cited path.
                continue

            line_start = cls._optional_int(item.get("line_start"))
            line_end = cls._optional_int(item.get("line_end"))

            actual_start = matching_chunk.get("line_start")
            actual_end = matching_chunk.get("line_end")

            if line_start is not None and actual_start is not None:
                if line_start < actual_start:
                    continue

            if line_end is not None and actual_end is not None:
                if line_end > actual_end:
                    continue

            evidence = VerifiedEvidence(
                path=path,
                quote=quote,
                claim=claim,
                line_start=line_start,
                line_end=line_end,
            )

            signature = (path, quote, claim)
            if signature not in seen:
                seen.add(signature)
                verified.append(evidence)

        return verified

    @staticmethod
    def _contains_exact_quote(
        source: str,
        quote: str,
    ) -> bool:
        def normalize(text: str) -> str:
            return re.sub(r"\s+", " ", text).strip()

        normalized_source = normalize(source)
        normalized_quote = normalize(quote)

        return bool(
            normalized_quote
            and normalized_quote in normalized_source
        )

    # ------------------------------------------------------------------
    # Validate follow-up targets against the existing dependency graph
    # ------------------------------------------------------------------

    def _resolve_follow_up_targets(
        self,
        *,
        raw_targets: Any,
        graph: Any,
    ) -> list[str]:
        if not isinstance(raw_targets, (list, tuple)):
            return []

        nodes = self._graph_nodes(graph)
        if not nodes:
            return []

        known_ids = set(nodes)
        known_paths: dict[str, list[str]] = {}

        for node_id, node in nodes.items():
            path = self._field(node, "path")
            if isinstance(path, str):
                try:
                    normalized_path = self._normalize_path(path)
                except ValueError:
                    continue

                known_paths.setdefault(normalized_path, []).append(node_id)

        output: list[str] = []
        seen: set[str] = set()

        for raw_target in raw_targets:
            candidate_ids: list[str] = []

            if isinstance(raw_target, str):
                value = raw_target.strip()

                if value in known_ids:
                    candidate_ids = [value]
                else:
                    try:
                        path = self._normalize_path(value)
                    except ValueError:
                        continue

                    # A repository-relative path is accepted only if it
                    # uniquely maps to an existing graph node.
                    matches = known_paths.get(path, [])
                    file_nodes = [
                        node_id
                        for node_id in matches
                        if self._field(nodes[node_id], "kind") == "file"
                        or node_id == f"file:{path}"
                    ]

                    if len(file_nodes) == 1:
                        candidate_ids = file_nodes

            elif isinstance(raw_target, Mapping):
                explicit_id = raw_target.get(
                    "node_id",
                    raw_target.get("id"),
                )

                if isinstance(explicit_id, str) and explicit_id in known_ids:
                    candidate_ids = [explicit_id]
                else:
                    raw_path = raw_target.get("path")
                    raw_name = raw_target.get("name")

                    if not isinstance(raw_path, str):
                        continue

                    try:
                        path = self._normalize_path(raw_path)
                    except ValueError:
                        continue

                    matches = known_paths.get(path, [])

                    if isinstance(raw_name, str) and raw_name.strip():
                        matching_symbols = [
                            node_id
                            for node_id in matches
                            if self._field(nodes[node_id], "name")
                            == raw_name.strip()
                            and self._field(nodes[node_id], "kind")
                            in {"function", "method", "class"}
                        ]

                        if len(matching_symbols) == 1:
                            candidate_ids = matching_symbols
                    else:
                        file_nodes = [
                            node_id
                            for node_id in matches
                            if self._field(nodes[node_id], "kind") == "file"
                            or node_id == f"file:{path}"
                        ]

                        if len(file_nodes) == 1:
                            candidate_ids = file_nodes

            for node_id in candidate_ids:
                if node_id not in seen:
                    seen.add(node_id)
                    output.append(node_id)

                if len(output) >= self.max_follow_up_targets:
                    return output

        return output

    @staticmethod
    def _graph_nodes(graph: Any) -> dict[str, Any]:
        """
        Support DependencyGraph instances and their to_dict() representation.
        """
        if graph is None:
            return {}

        nodes = getattr(graph, "nodes", None)

        if isinstance(nodes, Mapping):
            return dict(nodes)

        if isinstance(graph, Mapping):
            nodes = graph.get("nodes")
            if isinstance(nodes, Mapping):
                return dict(nodes)

        return {}

    @staticmethod
    def _field(value: Any, name: str) -> Any:
        if isinstance(value, Mapping):
            return value.get(name)

        return getattr(value, name, None)

    # ------------------------------------------------------------------
    # General normalization
    # ------------------------------------------------------------------

    @classmethod
    def _normalize_chunks(cls, raw_chunks: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_chunks, (list, tuple)):
            return []

        normalized: list[dict[str, Any]] = []
        seen: set[tuple[str, str, Optional[int]]] = set()

        for item in raw_chunks:
            if not isinstance(item, Mapping):
                continue

            raw_path = item.get("path")
            content = item.get("content", item.get("code"))

            if not isinstance(raw_path, str):
                continue

            if not isinstance(content, str) or not content.strip():
                continue

            try:
                path = cls._normalize_path(raw_path)
            except ValueError:
                continue

            line_start = cls._optional_int(item.get("line_start"))
            line_end = cls._optional_int(item.get("line_end"))

            signature = (path, content, line_start)
            if signature in seen:
                continue
            seen.add(signature)

            normalized.append(
                {
                    "path": path,
                    "content": content,
                    "line_start": line_start,
                    "line_end": line_end,
                }
            )

        return normalized

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

    @staticmethod
    def _read_confidence(value: Any) -> float:
        if isinstance(value, bool):
            return 0.0

        if isinstance(value, (int, float)):
            return max(0.0, min(1.0, float(value)))

        return 0.0

    @staticmethod
    def _read_nonnegative_int(
        value: Any,
        *,
        default: int,
    ) -> int:
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value

        return default

    @staticmethod
    def _read_positive_int(
        value: Any,
        *,
        default: int,
    ) -> int:
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value

        return default

    @staticmethod
    def _json_safe(value: Any) -> Any:
        """Convert common graph objects into mapping/list data for adapters."""
        if value is None or isinstance(
            value, (str, int, float, bool)
        ):
            return value

        if isinstance(value, Mapping):
            return {
                str(key): DeepSearchAssessor._json_safe(item)
                for key, item in value.items()
            }

        if isinstance(value, (list, tuple, set)):
            return [
                DeepSearchAssessor._json_safe(item)
                for item in value
            ]

        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            try:
                return DeepSearchAssessor._json_safe(to_dict())
            except Exception:
                return repr(value)

        if hasattr(value, "__dataclass_fields__"):
            from dataclasses import asdict

            try:
                return DeepSearchAssessor._json_safe(asdict(value))
            except Exception:
                return repr(value)

        return repr(value)

    # ------------------------------------------------------------------
    # Consistent terminal outcomes
    # ------------------------------------------------------------------

    @staticmethod
    def _incomplete(*, reason: str) -> dict[str, Any]:
        return AssessmentResult(
            status="incomplete",
            diagnosis=None,
            confidence=0.0,
            evidence=(),
            follow_up_targets=(),
            follow_up_query=None,
            reason=reason,
        ).to_dict()

    @staticmethod
    def _unavailable(reason: str) -> dict[str, Any]:
        return AssessmentResult(
            status="unavailable",
            diagnosis=None,
            confidence=0.0,
            evidence=(),
            follow_up_targets=(),
            follow_up_query=None,
            reason=reason,
        ).to_dict()
