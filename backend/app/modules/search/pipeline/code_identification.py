
"""
app/modules/search/pipeline/code_identification.py

Pipeline stage: Code Identification.

Identifies the target code element from retrieved chunks.

Design:
- Use the LLM when available.
- If the LLM fails, use deterministic identification.
- Never guess a target when deterministic evidence is insufficient.
- Preserve ambiguity when the same symbol exists in multiple files.
- Retrieval score alone must never resolve a same-symbol conflict.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from app.core.logging import get_logger
from app.modules.llm.service.llm_service import LLMService
from app.modules.search.domain.search_domain import (
    RetrievedChunk,
    SearchContext,
)

logger = get_logger(__name__)


_IDENTIFIER_RE = re.compile(
    r"\b[A-Za-z_][A-Za-z0-9_]*\b"
)

_FILE_PATH_RE = re.compile(
    r"(?:[\w.-]+[\\/])*[\w.-]+\."
    r"(?:ts|tsx|js|jsx|py|java|go|rs|cpp|c|h|hpp|cs|"
    r"json|yaml|yml|xml|html|css|scss|sql|md|env)"
    r"\b",
    re.IGNORECASE,
)


@dataclass
class _CandidateTarget:
    """Represents a unique candidate code target."""

    symbol_name: str
    file_path: str
    class_name: str | None
    primary_chunk: RetrievedChunk
    element: dict[str, Any] | None
    score: float
    has_symbol_match: bool = False


class CodeIdentificationStage:
    """Identify the target code element from retrieved chunks."""

    def __init__(
        self,
        llm_service: LLMService,
    ) -> None:
        self.llm_service = llm_service

    async def execute(self, context: SearchContext) -> None:
        if context.early_exit:
            return

        if not context.retrieved_chunks:
            context.early_exit = "EARLY_EXIT_C"
            context.early_exit_message = (
                "Could not identify specific code elements because "
                "no relevant code was retrieved."
            )
            return

        elements = await self._identify(context)

        if not elements:
            # Retrieval evidence is still useful when the LLM cannot name a
            # symbol. Preserve it for analysis and validation instead of
            # stopping the complete pipeline at code identification.
            primary_chunk = context.retrieved_chunks[0]
            context.primary_chunk = primary_chunk
            context.target_symbol = (
                primary_chunk.metadata.get("function_name")
                or primary_chunk.metadata.get("class_name")
                or primary_chunk.metadata.get("symbol")
                or None
            )
            context.identified_elements = []
            logger.warning(
                "code_identification_unresolved_using_retrieved_context",
                repo_id=context.repo_id,
                file_path=primary_chunk.file_path,
            )
            return

        valid_elements = [
            element
            for element in elements
            if isinstance(element, dict)
            and str(element.get("name") or "").strip()
        ]

        if not valid_elements:
            conflict_detected = self._detect_symbol_conflict(
                context,
                valid_elements=[],
            )

            if conflict_detected and context.ambiguous_candidates:
                self._mark_ambiguous(
                    context,
                    (
                        "Ambiguous code target: multiple candidates with "
                        "the same symbol were found across different files."
                    ),
                )
                return

            context.early_exit = "EARLY_EXIT_C"
            context.early_exit_message = (
                "Code identification returned no valid code elements."
            )
            return

        context.identified_elements = valid_elements

        # ---------------------------------------------------------
        # SAME-SYMBOL CANDIDATE DISCOVERY
        # ---------------------------------------------------------
        conflict_detected = self._detect_symbol_conflict(
            context,
            valid_elements,
        )

        if conflict_detected:
            context.symbol_conflict = True

            logger.info(
                "code_identification_symbol_candidates_found",
                query=context.query,
                candidate_count=len(
                    context.ambiguous_candidates
                ),
                candidates=[
                    {
                        "name": candidate["name"],
                        "file": candidate["file_path"],
                        "class": candidate.get("class_name"),
                    }
                    for candidate in context.ambiguous_candidates
                ],
            )

        # ---------------------------------------------------------
        # RESOLVE TARGET
        # ---------------------------------------------------------
        (
            selected_element,
            primary_chunk,
            is_ambiguous,
            reason,
        ) = self._resolve_target(
            context,
            valid_elements,
        )

        if is_ambiguous:
            self._mark_ambiguous(
                context,
                reason
                or (
                    "Could not uniquely identify the code target "
                    "because multiple plausible candidates were found."
                ),
            )

            logger.warning(
                "code_identification_ambiguous_targets",
                repo_id=context.repo_id,
                query=context.query,
                reason=context.early_exit_message,
            )
            return

        if not selected_element or not primary_chunk:
            context.early_exit = "EARLY_EXIT_C"
            context.early_exit_message = (
                "Code identification could not find a matching "
                "code target in retrieved chunks."
            )
            return

        # ---------------------------------------------------------
        # SUCCESSFUL IDENTIFICATION
        # ---------------------------------------------------------
        context.ambiguous = False
        context.is_ambiguous = False

        context.target_symbol = selected_element.get("name")
        context.primary_chunk = primary_chunk

        logger.info(
            "code_identification_complete",
            repo_id=context.repo_id,
            elements=len(valid_elements),
            target_symbol=context.target_symbol,
            primary_file=(
                context.primary_chunk.file_path
                if context.primary_chunk
                else None
            ),
            symbol_conflict=context.symbol_conflict,
        )

    async def _identify(
        self,
        context: SearchContext,
    ) -> list[dict[str, Any]]:
        """
        Identify code elements using the LLM.

        If LLM identification fails, use deterministic fallback.
        The fallback is intentionally conservative.
        """

        chunks = context.retrieved_chunks

        if not chunks:
            return []

        try:
            elements = await self.llm_service.identify_code_elements(
                context.query,
                chunks,
            )

            if isinstance(elements, list):
                valid_elements = [
                    element
                    for element in elements
                    if isinstance(element, dict)
                    and str(element.get("name") or "").strip()
                ]

                if valid_elements:
                    return valid_elements

                logger.warning(
                    "code_identification_llm_returned_no_valid_elements",
                    repo_id=context.repo_id,
                )

        except Exception:
            logger.exception(
                "code_identification_llm_failed_using_fallback",
                repo_id=context.repo_id,
            )

        return _fallback_identification(
            context.query,
            chunks,
        )

    def _detect_symbol_conflict(
        self,
        context: SearchContext,
        valid_elements: list[dict[str, Any]],
    ) -> bool:
        """
        Discover whether the same exact symbol exists in multiple files.

        This method does NOT decide whether the query is ambiguous.

        It only:
        - discovers exact symbol/file matches
        - stores candidates
        - reports whether a same-symbol multi-file conflict exists
        """

        chunks = context.retrieved_chunks

        if not chunks:
            return False

        # An explicit file already resolves the file dimension.
        if context.file_paths:
            return False

        queried_names: set[str] = set()

        # Symbols returned by LLM/deterministic identification.
        for element in valid_elements:
            name = str(
                element.get("name") or ""
            ).strip().lower()

            if name:
                queried_names.add(name)

        # Symbols present in retrieved metadata.
        for chunk in chunks:
            metadata = chunk.metadata or {}

            for key in (
                "function_name",
                "class_name",
                "symbol",
            ):
                value = str(
                    metadata.get(key) or ""
                ).strip().lower()

                if value and value not in {
                    "none",
                    "unknown",
                    "anonymous",
                }:
                    queried_names.add(value)

        if not queried_names:
            return False

        matches_by_file: dict[
            tuple[str, str],
            dict[str, Any],
        ] = {}

        for chunk in chunks:
            metadata = chunk.metadata or {}

            chunk_file = _normalize_path(
                chunk.file_path
            )

            function_name = _normalize_name(
                metadata.get("function_name")
            )

            class_name = _normalize_name(
                metadata.get("class_name")
            )

            symbol = _normalize_name(
                metadata.get("symbol")
            )

            metadata_symbols = {
                value
                for value in (
                    function_name,
                    class_name,
                    symbol,
                )
                if value
            }

            for queried_name in queried_names:
                if queried_name not in metadata_symbols:
                    continue

                key = (
                    queried_name,
                    chunk_file,
                )

                candidate = {
                    "name": (
                        metadata.get("function_name")
                        or metadata.get("class_name")
                        or metadata.get("symbol")
                        or queried_name
                    ),
                    "file_path": chunk.file_path,
                    "class_name": (
                        str(
                            metadata.get("class_name")
                            or ""
                        ).strip()
                        or None
                    ),
                    "start_line": metadata.get(
                        "start_line"
                    ),
                    "end_line": metadata.get(
                        "end_line"
                    ),
                    "score": chunk.score,
                }

                if (
                    key not in matches_by_file
                    or chunk.score
                    > matches_by_file[key]["score"]
                ):
                    matches_by_file[key] = candidate

        if not matches_by_file:
            return False

        by_name: dict[
            str,
            list[dict[str, Any]],
        ] = {}

        for (
            name_lower,
            _file_lower,
        ), candidate in matches_by_file.items():
            by_name.setdefault(
                name_lower,
                [],
            ).append(candidate)

        conflict_candidates: list[
            dict[str, Any]
        ] = []

        for file_matches in by_name.values():
            unique_files = {
                _normalize_path(
                    candidate["file_path"]
                )
                for candidate in file_matches
            }

            if len(unique_files) >= 2:
                conflict_candidates.extend(
                    file_matches
                )

        if not conflict_candidates:
            return False

        conflict_candidates.sort(
            key=lambda candidate: (
                candidate.get("score") or 0.0
            ),
            reverse=True,
        )

        context.ambiguous_candidates = (
            _deduplicate_candidate_dicts(
                conflict_candidates
            )
        )

        return True

    def _resolve_target(
        self,
        context: SearchContext,
        valid_elements: list[dict[str, Any]],
    ) -> tuple[
        dict[str, Any] | None,
        RetrievedChunk | None,
        bool,
        str | None,
    ]:
        """
        Resolve the requested code target.

        Resolution order:

        1. Explicit file/path
        2. Explicit class
        3. Strong contextual/domain evidence
        4. Explicit symbol
        5. Retrieval score only when there is no same-symbol conflict

        Same-symbol candidates across different files are never
        resolved by retrieval score alone.
        """

        chunks = context.retrieved_chunks

        if not chunks:
            return None, None, False, None

        candidates = self._extract_candidate_targets(
            chunks,
            valid_elements,
        )

        if not candidates:
            return None, None, False, None

        if context.symbol_conflict:
            plausible = [
                candidate
                for candidate in candidates
                if candidate.has_symbol_match
            ]

            if not plausible:
                plausible = candidates
        else:
            plausible = self._filter_plausible_candidates(
                candidates
            )

        if not plausible:
            return None, None, False, None

        # ---------------------------------------------------------
        # Single candidate
        # ---------------------------------------------------------
        if len(plausible) == 1:
            chosen = plausible[0]

            element = (
                chosen.element
                or {
                    "name": chosen.symbol_name,
                    "file_path": chosen.file_path,
                }
            )

            primary_chunk = self._find_primary_chunk(
                chunks,
                element,
            ) or chosen.primary_chunk

            return (
                element,
                primary_chunk,
                False,
                None,
            )

        # ---------------------------------------------------------
        # Multiple candidates
        # ---------------------------------------------------------
        scored = [
            (
                self._compute_disambiguation_score(
                    candidate,
                    context,
                ),
                candidate,
            )
            for candidate in plausible
        ]

        scored.sort(
            key=lambda item: (
                item[0],
                item[1].score,
            ),
            reverse=True,
        )

        top_context_score, top_candidate = scored[0]
        second_context_score, second_candidate = scored[1]

        context_gap = (
            top_context_score
            - second_context_score
        )

        # ---------------------------------------------------------
        # Strong contextual discriminator.
        # ---------------------------------------------------------
        if (
            top_context_score > 0
            and context_gap >= 3.0
        ):
            element = (
                top_candidate.element
                or {
                    "name": top_candidate.symbol_name,
                    "file_path": top_candidate.file_path,
                }
            )

            primary_chunk = self._find_primary_chunk(
                chunks,
                element,
            ) or top_candidate.primary_chunk

            return (
                element,
                primary_chunk,
                False,
                None,
            )

        # ---------------------------------------------------------
        # Retrieval score can only resolve NON-CONFLICT cases.
        # ---------------------------------------------------------
        if not context.symbol_conflict:
            score_diff = (
                top_candidate.score
                - second_candidate.score
            )

            if (
                score_diff >= 0.20
                and (
                    second_candidate.score <= 0
                    or second_candidate.score
                    < 0.65 * top_candidate.score
                )
            ):
                element = (
                    top_candidate.element
                    or {
                        "name": top_candidate.symbol_name,
                        "file_path": top_candidate.file_path,
                    }
                )

                primary_chunk = self._find_primary_chunk(
                    chunks,
                    element,
                ) or top_candidate.primary_chunk

                return (
                    element,
                    primary_chunk,
                    False,
                    None,
                )

        # ---------------------------------------------------------
        # Ambiguous
        # ---------------------------------------------------------
        context.ambiguous_candidates = (
            self._build_ambiguity_candidates(
                scored,
                context,
            )
        )

        candidate_descriptions = []

        for candidate in context.ambiguous_candidates[:10]:
            description = (
                f"'{candidate.get('name')}'"
            )

            if candidate.get("class_name"):
                description += (
                    f" in class "
                    f"'{candidate.get('class_name')}'"
                )

            description += (
                f" ({candidate.get('file_path')})"
            )

            candidate_descriptions.append(
                description
            )

        reason = (
            "Ambiguous code target: multiple plausible "
            "candidates were found and the query does not "
            "provide enough information to uniquely identify "
            "the target: "
            f"{'; '.join(candidate_descriptions)}."
        )

        return (
            None,
            None,
            True,
            reason,
        )

    @staticmethod
    def _extract_candidate_targets(
        chunks: list[RetrievedChunk],
        valid_elements: list[dict[str, Any]],
    ) -> list[_CandidateTarget]:
        """
        Extract unique candidate targets.

        Candidate identity:
            symbol + file + class
        """

        candidates_by_key: dict[
            tuple[str, str, str],
            _CandidateTarget,
        ] = {}

        for element in valid_elements:
            element_name = str(
                element.get("name") or ""
            ).strip()

            element_file = _normalize_path(
                element.get("file_path")
            )

            if not element_name:
                continue

            for chunk in chunks:
                metadata = chunk.metadata or {}

                chunk_file = _normalize_path(
                    chunk.file_path
                )

                function_name = str(
                    metadata.get("function_name")
                    or ""
                ).strip()

                class_name = str(
                    metadata.get("class_name")
                    or ""
                ).strip()

                symbol = str(
                    metadata.get("symbol")
                    or ""
                ).strip()

                metadata_symbols = {
                    function_name.lower(),
                    class_name.lower(),
                    symbol.lower(),
                }

                is_symbol_match = (
                    element_name.lower()
                    in metadata_symbols
                )

                is_file_match = bool(
                    element_file
                    and _paths_match(
                        element_file,
                        chunk_file,
                    )
                )

                if not (
                    is_symbol_match
                    or is_file_match
                ):
                    continue

                chosen_symbol = (
                    function_name
                    or class_name
                    or symbol
                    or element_name
                )

                key = (
                    chosen_symbol.lower(),
                    chunk_file,
                    class_name.lower(),
                )

                existing = candidates_by_key.get(
                    key
                )

                if existing is None:
                    candidates_by_key[key] = (
                        _CandidateTarget(
                            symbol_name=chosen_symbol,
                            file_path=chunk.file_path,
                            class_name=(
                                class_name
                                or None
                            ),
                            primary_chunk=chunk,
                            element=element,
                            score=chunk.score,
                            has_symbol_match=(
                                is_symbol_match
                            ),
                        )
                    )
                    continue

                if chunk.score > existing.score:
                    existing.primary_chunk = chunk
                    existing.score = chunk.score

                if is_symbol_match:
                    existing.has_symbol_match = True

        return list(
            candidates_by_key.values()
        )

    @staticmethod
    def _filter_plausible_candidates(
        candidates: list[_CandidateTarget],
    ) -> list[_CandidateTarget]:
        """
        Filter weak candidates for non-conflict cases.
        """

        if not candidates:
            return []

        symbol_matched = [
            candidate
            for candidate in candidates
            if candidate.has_symbol_match
        ]

        pool = (
            symbol_matched
            if symbol_matched
            else candidates
        )

        if not pool:
            return []

        symbol_files = {
            _normalize_path(
                candidate.file_path
            )
            for candidate in pool
        }

        if len(symbol_files) > 1:
            return pool

        max_score = max(
            candidate.score
            for candidate in pool
        )

        plausible = [
            candidate
            for candidate in pool
            if (
                candidate.score
                >= max_score - 0.20
                or candidate.score
                >= 0.70 * max_score
                or (
                    candidate.has_symbol_match
                    and candidate.score >= 0.30
                )
            )
        ]

        return (
            plausible
            if plausible
            else pool
        )

    @staticmethod
    def _compute_disambiguation_score(
        candidate: _CandidateTarget,
        context: SearchContext,
    ) -> float:
        """
        Calculate deterministic query/context evidence.

        Retrieval score is intentionally excluded.
        """

        score = 0.0

        query_lower = (
            context.query or ""
        ).lower()

        query_tokens = {
            token.lower()
            for token in _IDENTIFIER_RE.findall(
                query_lower
            )
        }

        ctx_keywords = {
            str(keyword).strip().lower()
            for keyword in (
                context.keywords or []
            )
            if keyword
            and str(keyword).strip()
        }

        ctx_identifiers = {
            str(identifier).strip().lower()
            for identifier in (
                context.identifiers or []
            )
            if identifier
            and str(identifier).strip()
        }

        ctx_file_paths = [
            _normalize_path(file_path)
            for file_path in (
                context.file_paths or []
            )
            if file_path
            and str(file_path).strip()
        ]

        candidate_file = _normalize_path(
            candidate.file_path
        )

        candidate_filename = (
            candidate_file.split("/")[-1]
        )

        candidate_stem = (
            candidate_filename.rsplit(
                ".",
                1,
            )[0]
            if "." in candidate_filename
            else candidate_filename
        )

        candidate_dir_parts = [
            part
            for part in candidate_file.split("/")[:-1]
            if part
            and part not in {
                "app",
                "src",
                "lib",
                "test",
                "tests",
                "backend",
                "modules",
                "service",
                "services",
                "pipeline",
                "domain",
            }
        ]

        candidate_symbol = (
            candidate.symbol_name.lower()
        )

        candidate_class = (
            candidate.class_name or ""
        ).lower()

        # ---------------------------------------------------------
        # 1. Explicit file path
        # ---------------------------------------------------------
        for file_path in ctx_file_paths:
            if _paths_match(
                file_path,
                candidate_file,
            ):
                score += 20.0
                break

            file_name = file_path.split("/")[-1]

            if (
                candidate_filename == file_name
                or candidate_stem == file_name
            ):
                score += 16.0
                break

        # ---------------------------------------------------------
        # File/stem mentioned in extracted terms
        # ---------------------------------------------------------
        if (
            candidate_filename in ctx_identifiers
            or candidate_filename in ctx_keywords
        ):
            score += 12.0

        elif (
            candidate_stem in ctx_identifiers
            or candidate_stem in ctx_keywords
        ):
            score += 10.0

        # ---------------------------------------------------------
        # File/stem directly mentioned in query
        # ---------------------------------------------------------
        if candidate_filename in query_tokens:
            score += 10.0

        elif (
            candidate_stem in query_tokens
            and len(candidate_stem) > 2
        ):
            score += 8.0

        # ---------------------------------------------------------
        # Directory/domain
        # ---------------------------------------------------------
        for part in candidate_dir_parts:
            if part in ctx_file_paths:
                score += 8.0

            elif (
                part in ctx_identifiers
                or part in ctx_keywords
            ):
                score += 6.0

            elif (
                part in query_tokens
                and len(part) > 2
            ):
                score += 4.0

        # ---------------------------------------------------------
        # 2. Class name
        # ---------------------------------------------------------
        if candidate_class:
            if candidate_class in ctx_identifiers:
                score += 16.0

            if candidate_class in ctx_keywords:
                score += 10.0

            if candidate_class in query_tokens:
                score += 12.0

            normalized_class = _split_camel_case(
                candidate.class_name or ""
            )

            query_without_punctuation = re.sub(
                r"[^a-z0-9_ ]+",
                " ",
                query_lower,
            )

            if normalized_class in query_without_punctuation:
                score += 10.0

            for class_token in normalized_class.split():
                if (
                    len(class_token) > 2
                    and class_token in query_tokens
                ):
                    score += 3.0

        # ---------------------------------------------------------
        # 3. Symbol
        # ---------------------------------------------------------
        if candidate_symbol in ctx_identifiers:
            score += 8.0

        if candidate_symbol in query_tokens:
            score += 6.0

        # ---------------------------------------------------------
        # 4. LLM element file match
        # ---------------------------------------------------------
        if candidate.element:
            element_file = _normalize_path(
                candidate.element.get(
                    "file_path"
                )
            )

            if (
                element_file
                and _paths_match(
                    element_file,
                    candidate_file,
                )
            ):
                score += 8.0

        # ---------------------------------------------------------
        # 5. Keyword/domain overlap
        # ---------------------------------------------------------
        for keyword in ctx_keywords:
            if len(keyword) <= 2:
                continue

            if (
                keyword in candidate_symbol
                or keyword in candidate_class
                or keyword in candidate_filename
                or keyword in candidate_stem
            ):
                score += 3.0

        return score

    @staticmethod
    def _build_ambiguity_candidates(
        scored: list[
            tuple[float, _CandidateTarget]
        ],
        context: SearchContext,
    ) -> list[dict[str, Any]]:
        """
        Convert internal candidates into the public ambiguity format.
        """

        if (
            context.symbol_conflict
            and context.ambiguous_candidates
        ):
            return _deduplicate_candidate_dicts(
                context.ambiguous_candidates
            )

        candidates = []

        for _, candidate in scored[:10]:
            metadata = (
                candidate.primary_chunk.metadata
                or {}
            )

            candidates.append(
                {
                    "name": candidate.symbol_name,
                    "file_path": candidate.file_path,
                    "class_name": candidate.class_name,
                    "start_line": metadata.get(
                        "start_line"
                    ),
                    "end_line": metadata.get(
                        "end_line"
                    ),
                    "score": candidate.score,
                }
            )

        return _deduplicate_candidate_dicts(
            candidates
        )

    @staticmethod
    def _find_primary_chunk(
        chunks: list[RetrievedChunk],
        element: dict[str, Any],
    ) -> RetrievedChunk | None:
        """
        Find the primary retrieved chunk for the identified element.

        Priority:
        1. Exact file + symbol
        2. Exact file
        3. Exact symbol
        4. Highest-scoring chunk
        """

        if not chunks:
            return None

        name = str(
            element.get("name") or ""
        ).strip().lower()

        file_hint = _normalize_path(
            element.get("file_path")
        )

        # ---------------------------------------------------------
        # 1. Exact file + symbol
        # ---------------------------------------------------------
        if file_hint and name:
            for chunk in chunks:
                chunk_file = _normalize_path(
                    chunk.file_path
                )

                if chunk_file != file_hint:
                    continue

                metadata = chunk.metadata or {}

                metadata_names = {
                    str(
                        metadata.get("function_name")
                        or ""
                    ).strip().lower(),
                    str(
                        metadata.get("class_name")
                        or ""
                    ).strip().lower(),
                    str(
                        metadata.get("symbol")
                        or ""
                    ).strip().lower(),
                }

                if name in metadata_names:
                    return chunk

        # ---------------------------------------------------------
        # 2. Exact file
        # ---------------------------------------------------------
        if file_hint:
            file_matches = [
                chunk
                for chunk in chunks
                if _normalize_path(
                    chunk.file_path
                ) == file_hint
            ]

            if file_matches:
                return max(
                    file_matches,
                    key=lambda chunk: chunk.score,
                )

        # ---------------------------------------------------------
        # 3. Exact symbol
        # ---------------------------------------------------------
        if name:
            matches = []

            for chunk in chunks:
                metadata = chunk.metadata or {}

                metadata_names = {
                    str(
                        metadata.get("function_name")
                        or ""
                    ).strip().lower(),
                    str(
                        metadata.get("class_name")
                        or ""
                    ).strip().lower(),
                    str(
                        metadata.get("symbol")
                        or ""
                    ).strip().lower(),
                }

                if name in metadata_names:
                    matches.append(chunk)

            if matches:
                return max(
                    matches,
                    key=lambda chunk: chunk.score,
                )

        # ---------------------------------------------------------
        # 4. Final fallback
        # ---------------------------------------------------------
        return max(
            chunks,
            key=lambda chunk: chunk.score,
        )

    @staticmethod
    def _mark_ambiguous(
        context: SearchContext,
        message: str,
    ) -> None:
        """Set the context to the standard ambiguity state."""

        context.symbol_conflict = (
            context.symbol_conflict
            or bool(context.ambiguous_candidates)
        )

        context.ambiguous = True
        context.is_ambiguous = True
        context.target_symbol = None
        context.primary_chunk = None
        context.early_exit = "EARLY_EXIT_C"
        context.early_exit_message = message


def _fallback_identification(
    query: str,
    chunks: list[RetrievedChunk],
) -> list[dict[str, Any]]:
    """
    Deterministic fallback when LLM identification fails.

    Rules:
    - Match explicit identifiers against metadata.
    - Match explicit file paths against retrieved chunks.
    - Match explicit class/function names.
    - Do NOT select a random retrieved chunk.
    - Do NOT infer a target merely from retrieval ranking.
    """

    if not query or not chunks:
        return []

    query = query.strip()

    identifiers = _extract_query_identifiers(
        query
    )

    file_paths = _extract_query_file_paths(
        query
    )

    # Remove generic natural-language terms.
    stop_words = {
        "find",
        "where",
        "what",
        "which",
        "show",
        "get",
        "retrieve",
        "locate",
        "identify",
        "fetch",
        "list",
        "search",
        "is",
        "are",
        "the",
        "this",
        "that",
        "a",
        "an",
        "in",
        "on",
        "at",
        "to",
        "from",
        "for",
        "of",
        "and",
        "or",
        "with",
        "used",
        "use",
        "using",
        "service",
        "class",
        "function",
        "method",
        "code",
        "add",
        "feature",
        "support",
        "improve",
        "implement",
        "create",
        "update",
        "modify",
        "fix",
        "bug",
        "issue",
        "error",
        "debug",
        "optimize",
        "optimise",
        "optimization",
        "optimisation",
        "refactor",
        "refactoring",
    }

    identifiers = [
        identifier
        for identifier in identifiers
        if identifier.lower()
        not in stop_words
    ]

    matches: list[dict[str, Any]] = []

    for chunk in chunks:
        metadata = chunk.metadata or {}

        function_name = str(
            metadata.get("function_name")
            or ""
        ).strip()

        class_name = str(
            metadata.get("class_name")
            or ""
        ).strip()

        symbol = str(
            metadata.get("symbol")
            or ""
        ).strip()

        metadata_names = {
            name.lower(): name
            for name in (
                function_name,
                class_name,
                symbol,
            )
            if name
        }

        # ---------------------------------------------------------
        # 1. Explicit file path + metadata symbol
        # ---------------------------------------------------------
        file_match = False

        chunk_file = _normalize_path(
            chunk.file_path
        )

        for requested_file in file_paths:
            if _paths_match(
                requested_file,
                chunk_file,
            ):
                file_match = True
                break

        if file_match:
            target_name = (
                _match_identifier_to_metadata(
                    identifiers,
                    metadata_names,
                )
            )

            if target_name:
                matches.append(
                    _build_fallback_element(
                        target_name,
                        chunk,
                        "deterministic_fallback",
                    )
                )
                continue

            # Explicit file but no symbol:
            # only return the file if the query clearly
            # names that file and there is exactly one
            # meaningful code element in it.
            target_name = (
                function_name
                or class_name
                or symbol
            )

            if target_name:
                matches.append(
                    _build_fallback_element(
                        target_name,
                        chunk,
                        "deterministic_file_fallback",
                    )
                )

                continue

        # ---------------------------------------------------------
        # 2. Exact identifier -> metadata symbol
        # ---------------------------------------------------------
        target_name = (
            _match_identifier_to_metadata(
                identifiers,
                metadata_names,
            )
        )

        if target_name:
            matches.append(
                _build_fallback_element(
                    target_name,
                    chunk,
                    "deterministic_fallback",
                )
            )

    # ---------------------------------------------------------
    # If no explicit candidate token in query matched metadata symbols,
    # extract code elements directly from retrieved chunks metadata.
    # ---------------------------------------------------------
    if not matches:
        for chunk in chunks:
            metadata = chunk.metadata or {}
            fname = str(metadata.get("function_name") or "").strip()
            cname = str(metadata.get("class_name") or "").strip()
            sym = str(metadata.get("symbol") or "").strip()
            target_name = fname or cname or sym
            if target_name:
                matches.append(
                    _build_fallback_element(
                        target_name,
                        chunk,
                        "deterministic_chunk_fallback",
                    )
                )

    # ---------------------------------------------------------
    # Deduplicate.
    # ---------------------------------------------------------
    unique_matches = _deduplicate_matches(
        matches
    )

    return unique_matches


def _extract_query_identifiers(
    query: str,
) -> list[str]:
    """
    Extract identifier-like tokens from a natural-language query.
    """

    identifiers = _IDENTIFIER_RE.findall(
        query
    )

    result: list[str] = []
    seen: set[str] = set()

    for identifier in identifiers:
        normalized = identifier.lower()

        if normalized in seen:
            continue

        seen.add(normalized)
        result.append(identifier)

    return result


def _extract_query_file_paths(
    query: str,
) -> list[str]:
    """Extract explicit source/config file paths."""

    matches = _FILE_PATH_RE.findall(
        query
    )

    result: list[str] = []
    seen: set[str] = set()

    for match in matches:
        normalized = _normalize_path(
            match
        )

        if normalized in seen:
            continue

        seen.add(normalized)
        result.append(normalized)

    return result


def _match_identifier_to_metadata(
    identifiers: list[str],
    metadata_names: dict[str, str],
) -> str | None:
    """
    Find an exact identifier-to-metadata match.

    Exact matching is intentional. We do not use fuzzy matching
    here because the fallback must not guess.
    """

    for identifier in identifiers:
        normalized = identifier.lower()

        if normalized in metadata_names:
            return metadata_names[
                normalized
            ]

    return None


def _build_fallback_element(
    name: str,
    chunk: RetrievedChunk,
    identification_method: str,
) -> dict[str, Any]:
    """Build a deterministic identification result."""

    metadata = chunk.metadata or {}

    return {
        "name": name,
        "file_path": chunk.file_path,
        "class_name": (
            str(
                metadata.get("class_name")
                or ""
            ).strip()
            or None
        ),
        "start_line": metadata.get(
            "start_line"
        ),
        "end_line": metadata.get(
            "end_line"
        ),
        "chunk_type": metadata.get(
            "chunk_type"
        ),
        "identification_method": identification_method,
    }


def _deduplicate_matches(
    matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Deduplicate identified elements by name + file."""

    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for match in matches:
        key = (
            str(
                match.get("name") or ""
            ).strip().lower(),
            _normalize_path(
                match.get("file_path")
            ),
        )

        if key in seen:
            continue

        seen.add(key)
        unique.append(match)

    return unique


def _deduplicate_candidate_dicts(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Deduplicate ambiguity candidates."""

    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for candidate in candidates:
        key = (
            str(
                candidate.get("name") or ""
            ).strip().lower(),
            _normalize_path(
                candidate.get("file_path")
            ),
        )

        if key in seen:
            continue

        seen.add(key)
        unique.append(candidate)

    return unique


def _normalize_name(
    value: Any,
) -> str:
    """Normalize a metadata symbol name."""

    return str(
        value or ""
    ).strip().lower()


def _normalize_path(
    value: Any,
) -> str:
    """Normalize Windows/Unix paths."""

    return (
        str(value or "")
        .strip()
        .lower()
        .replace("\\", "/")
    )


def _paths_match(
    left: str,
    right: str,
) -> bool:
    """
    Determine whether two normalized paths refer to the same file.

    Supports:
    - exact path
    - relative path suffix
    - filename-only hints
    """

    left = _normalize_path(left)
    right = _normalize_path(right)

    if not left or not right:
        return False

    if left == right:
        return True

    if right.endswith("/" + left):
        return True

    if left.endswith("/" + right):
        return True

    return (
        left.split("/")[-1]
        == right.split("/")[-1]
        and (
            "/" not in left
            or "/" not in right
        )
    )


def _split_camel_case(
    value: str,
) -> str:
    """
    Convert ProductService -> product service.

    This is only used for contextual scoring.
    """

    normalized = re.sub(
        r"(?<!^)(?=[A-Z])",
        " ",
        value,
    )

    normalized = re.sub(
        r"[_\-]+",
        " ",
        normalized,
    )

    return " ".join(
        normalized.lower().split()
    )

