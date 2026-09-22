"""
app/modules/search/pipeline/code_identification.py

Pipeline stage: Code Identification (Step 7).
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

MAX_BROADEN_ATTEMPTS = 2
INITIAL_BROADEN_LIMIT = 20


@dataclass
class _CandidateTarget:
    """Represents a unique candidate code target extracted from retrieved chunks."""

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
        code_ret_stage=None,
    ) -> None:
        self.llm_service = llm_service
        self.code_ret_stage = code_ret_stage

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

        broaden_attempt = 0

        while (
            not elements
            and broaden_attempt < MAX_BROADEN_ATTEMPTS
        ):
            broaden_attempt += 1

            await self._broaden_retrieval(
                context,
                broaden_attempt,
            )

            if context.retrieved_chunks:
                elements = await self._identify(context)

        if not elements:
            conflict_detected = self._detect_symbol_conflict(
                context,
                valid_elements=[],
            )
            if conflict_detected and context.ambiguous_candidates:
                context.symbol_conflict = True
                context.ambiguous = True
                context.is_ambiguous = True
                context.early_exit = "EARLY_EXIT_C"
                context.early_exit_message = (
                    "Ambiguous code target: multiple candidates with the same symbol "
                    "were found across different files."
                )
                return

            context.early_exit = "EARLY_EXIT_C"
            context.early_exit_message = (
                "Could not identify specific code elements matching "
                "your query after broadened retrieval."
            )
            return

        valid_elements = [
            element
            for element in elements
            if isinstance(element, dict)
            and element.get("name")
        ]

        if not valid_elements:
            conflict_detected = self._detect_symbol_conflict(
                context,
                valid_elements=[],
            )
            if conflict_detected and context.ambiguous_candidates:
                context.symbol_conflict = True
                context.ambiguous = True
                context.is_ambiguous = True
                context.early_exit = "EARLY_EXIT_C"
                context.early_exit_message = (
                    "Ambiguous code target: multiple candidates with the same symbol "
                    "were found across different files."
                )
                return

            context.early_exit = "EARLY_EXIT_C"
            context.early_exit_message = (
                "Code identification returned no valid code elements."
            )
            return

        context.identified_elements = valid_elements

        # ---------------------------------------------------------
        # SAME-NAME-MULTIPLE-FILES CANDIDATE DISCOVERY
        #
        # IMPORTANT:
        # Multiple occurrences of the same symbol do NOT
        # automatically mean ambiguity.
        #
        # Example:
        #
        #   ProductService.search()
        #   UserService.search()
        #   TransactionService.search()
        #
        # The query may still clearly identify ProductService.
        #
        # Therefore this method only discovers the conflict and
        # stores all candidates. _resolve_target() makes the
        # final identification decision.
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
                candidate_count=len(context.ambiguous_candidates),
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
        #
        # Resolution priority:
        #
        # 1. Explicit file/path
        # 2. Explicit class
        # 3. Domain/context clues
        # 4. Explicit symbol
        # 5. Retrieval score only when there is no same-symbol
        #    conflict
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
            context.ambiguous = True
            context.is_ambiguous = True
            context.target_symbol = None
            context.primary_chunk = None
            context.early_exit = "EARLY_EXIT_C"

            context.early_exit_message = (
                reason
                or (
                    "Could not uniquely identify code target "
                    "due to multiple ambiguous candidates."
                )
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

        # IMPORTANT:
        #
        # Do NOT reset symbol_conflict here.
        #
        # symbol_conflict=True can mean:
        #
        # "The same symbol existed in multiple files, but the
        #  query contained enough information to identify one."
        #
        # This is different from ambiguous=True.
        #
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
                    and element.get("name")
                ]

                if valid_elements:
                    return valid_elements

        except Exception:
            logger.exception(
                "code_identification_llm_failed_using_fallback",
                repo_id=context.repo_id,
            )

        return _fallback_identification(
            context.query,
            chunks,
        )

    async def _broaden_retrieval(
        self,
        context: SearchContext,
        attempt: int,
    ) -> None:
        if self.code_ret_stage is None:
            return

        broader_limit = INITIAL_BROADEN_LIMIT * (2 ** attempt)

        await self.code_ret_stage.execute(
            context,
            limit=broader_limit,
        )

    def _detect_symbol_conflict(
        self,
        context: SearchContext,
        valid_elements: list[dict[str, Any]],
    ) -> bool:
        """
        Discover whether a queried symbol exists in multiple files.

        IMPORTANT:
        This method DOES NOT decide ambiguity.

        It only:
        - finds all exact symbol matches
        - stores them in context.ambiguous_candidates
        - returns True when the same symbol exists in multiple files

        Final resolution is handled by _resolve_target().
        """

        chunks = context.retrieved_chunks

        if not chunks:
            return False

        # If the user already specified a file, there is no
        # unresolved file conflict.
        #
        # _resolve_target() will still use the file information.
        if context.file_paths:
            return False

        # ---------------------------------------------------------
        # Collect symbol names returned by the LLM/fallback
        # as well as all symbols present in retrieved chunks.
        # ---------------------------------------------------------
        queried_names: set[str] = set()

        for element in valid_elements:
            name = str(
                element.get("name", "")
            ).strip().lower()

            if name:
                queried_names.add(name)

        for chunk in chunks:
            metadata = chunk.metadata or {}
            for key in ("function_name", "class_name", "symbol"):
                val = str(metadata.get(key) or "").strip().lower()
                if val and val not in {"none", "unknown", "anonymous", ""}:
                    queried_names.add(val)

        if not queried_names:
            return False

        # ---------------------------------------------------------
        # Find exact symbol matches.
        #
        # Key:
        #   (symbol_name, file_path)
        #
        # Keep only the highest-scoring chunk for the same
        # symbol/file pair.
        # ---------------------------------------------------------
        matches_by_file: dict[
            tuple[str, str],
            dict[str, Any],
        ] = {}

        for chunk in chunks:
            metadata = chunk.metadata or {}

            chunk_file = (
                str(chunk.file_path or "")
                .strip()
                .lower()
                .replace("\\", "/")
            )

            function_name = str(
                metadata.get("function_name") or ""
            ).strip().lower()

            class_name = str(
                metadata.get("class_name") or ""
            ).strip().lower()

            symbol = str(
                metadata.get("symbol") or ""
            ).strip().lower()

            metadata_symbols = {
                function_name,
                class_name,
                symbol,
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
                        str(
                            metadata.get("function_name")
                            or metadata.get("class_name")
                            or metadata.get("symbol")
                            or queried_name
                        )
                    ),
                    "file_path": chunk.file_path,
                    "class_name": (
                        str(
                            metadata.get("class_name") or ""
                        )
                        or None
                    ),
                    "start_line": metadata.get("start_line"),
                    "end_line": metadata.get("end_line"),
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

        # ---------------------------------------------------------
        # Group candidates by symbol.
        # ---------------------------------------------------------
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

        # ---------------------------------------------------------
        # A symbol conflict exists only when the same symbol
        # exists in at least two different files.
        # ---------------------------------------------------------
        conflict_candidates: list[dict[str, Any]] = []

        for _name_lower, file_matches in by_name.items():
            unique_files = {
                str(candidate["file_path"])
                .strip()
                .lower()
                .replace("\\", "/")
                for candidate in file_matches
            }

            if len(unique_files) >= 2:
                conflict_candidates.extend(
                    file_matches
                )

        if not conflict_candidates:
            return False

        # Highest retrieval score first.
        conflict_candidates.sort(
            key=lambda candidate: candidate["score"],
            reverse=True,
        )

        context.ambiguous_candidates = (
            conflict_candidates
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

        Resolution priority:

        1. Explicit file/path match
        2. Explicit class name match
        3. Strong domain/context match
        4. Explicit symbol match
        5. Retrieval score only when there is no same-symbol
           conflict

        Multiple candidates do NOT automatically mean ambiguity.

        Example:

            "Add a feature to the ProductService to support
             product search by category."

        If search() exists in:

            product_service.ts
            user_service.ts
            transaction_service.ts

        ProductService is a strong discriminator.

        Therefore:

            product_service.ts::ProductService.search

        should be selected.

        But:

            "Add a feature to improve the search function."

        has no discriminator and should remain ambiguous.
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

        # ---------------------------------------------------------
        # IMPORTANT:
        #
        # When the same symbol exists in multiple files, preserve
        # ALL symbol-matched candidates.
        #
        # Do NOT let retrieval-score filtering remove candidates
        # before disambiguation.
        # ---------------------------------------------------------
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
        # Only one candidate
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

            return (
                element,
                chosen.primary_chunk,
                False,
                None,
            )

        # ---------------------------------------------------------
        # Multiple candidates.
        #
        # Use query/context information to resolve them.
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
        # Strong explicit/context discriminator.
        #
        # This is preferred over retrieval score.
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

            return (
                element,
                top_candidate.primary_chunk,
                False,
                None,
            )

        # ---------------------------------------------------------
        # Retrieval score fallback.
        #
        # ONLY allowed when there is no same-symbol conflict.
        #
        # If search() exists in multiple files, retrieval score
        # alone must never decide which search() the user meant.
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

                return (
                    element,
                    top_candidate.primary_chunk,
                    False,
                    None,
                )

        # ---------------------------------------------------------
        # Still ambiguous.
        # ---------------------------------------------------------
        candidate_descriptions = []

        if context.symbol_conflict and context.ambiguous_candidates:
            for cand in context.ambiguous_candidates[:10]:
                description = f"'{cand.get('name')}'"
                if cand.get("class_name"):
                    description += f" in class '{cand.get('class_name')}'"
                description += f" ({cand.get('file_path')})"
                candidate_descriptions.append(description)
        else:
            for _, candidate in scored[:10]:
                description = (
                    f"'{candidate.symbol_name}'"
                )

                if candidate.class_name:
                    description += (
                        f" in class "
                        f"'{candidate.class_name}'"
                    )

                description += (
                    f" ({candidate.file_path})"
                )

                candidate_descriptions.append(
                    description
                )

        # ---------------------------------------------------------
        # Populate structured ambiguity candidates.
        # ---------------------------------------------------------
        if context.symbol_conflict and context.ambiguous_candidates:
            # Preserve the conflicting candidates identified across multiple files
            seen_cand: set[tuple[str, str]] = set()
            deduped_candidates: list[dict[str, Any]] = []
            for cand in context.ambiguous_candidates:
                cand_key = (
                    str(cand.get("name") or "").lower(),
                    str(cand.get("file_path") or "").lower(),
                )
                if cand_key not in seen_cand:
                    seen_cand.add(cand_key)
                    deduped_candidates.append(cand)
            context.ambiguous_candidates = deduped_candidates
        else:
            context.ambiguous_candidates = [
                {
                    "name": candidate.symbol_name,
                    "file_path": candidate.file_path,
                    "class_name": candidate.class_name,
                    "start_line": (
                        candidate.primary_chunk.metadata.get(
                            "start_line"
                        )
                        if (
                            candidate.primary_chunk
                            and candidate.primary_chunk.metadata
                        )
                        else None
                    ),
                    "end_line": (
                        candidate.primary_chunk.metadata.get(
                            "end_line"
                        )
                        if (
                            candidate.primary_chunk
                            and candidate.primary_chunk.metadata
                        )
                        else None
                    ),
                    "score": candidate.score,
                }
                for _, candidate in scored[:10]
            ]

        reason = (
            "Ambiguous code target: multiple plausible "
            "candidates were found and the query does not "
            "provide enough information to uniquely identify "
            f"the target: "
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
        Extract unique candidate targets from retrieved chunks.

        A candidate is identified by:

            symbol + file + class
        """

        candidates_by_key: dict[
            tuple[str, str, str],
            _CandidateTarget,
        ] = {}

        for element in valid_elements:
            element_name = str(
                element.get("name", "")
            ).strip()

            element_file = (
                str(
                    element.get("file_path", "")
                )
                .strip()
                .lower()
                .replace("\\", "/")
            )

            if not element_name:
                continue

            for chunk in chunks:
                metadata = chunk.metadata or {}

                chunk_file = (
                    str(chunk.file_path or "")
                    .strip()
                    .lower()
                    .replace("\\", "/")
                )

                function_name = str(
                    metadata.get("function_name") or ""
                ).strip()

                class_name = str(
                    metadata.get("class_name") or ""
                ).strip()

                symbol = str(
                    metadata.get("symbol") or ""
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
                    and (
                        element_file == chunk_file
                        or chunk_file.endswith(element_file)
                        or element_file in chunk_file
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

                if key not in candidates_by_key:
                    candidates_by_key[key] = (
                        _CandidateTarget(
                            symbol_name=chosen_symbol,
                            file_path=chunk.file_path,
                            class_name=class_name or None,
                            primary_chunk=chunk,
                            element=element,
                            score=chunk.score,
                            has_symbol_match=is_symbol_match,
                        )
                    )

                else:
                    existing = candidates_by_key[key]

                    if chunk.score > existing.score:
                        existing.primary_chunk = chunk
                        existing.score = chunk.score

                    if is_symbol_match:
                        existing.has_symbol_match = True

        # ---------------------------------------------------------
        # Fallback:
        #
        # If nothing matched the identified symbol, construct
        # candidates from retrieved chunks.
        # ---------------------------------------------------------
        if not candidates_by_key:
            default_element = (
                valid_elements[0]
                if valid_elements
                else None
            )

            for chunk in chunks:
                metadata = chunk.metadata or {}

                chunk_file = (
                    str(chunk.file_path or "")
                    .strip()
                    .lower()
                    .replace("\\", "/")
                )

                function_name = str(
                    metadata.get("function_name") or ""
                ).strip()

                class_name = str(
                    metadata.get("class_name") or ""
                ).strip()

                symbol = str(
                    metadata.get("symbol") or ""
                ).strip()

                chosen_symbol = (
                    function_name
                    or class_name
                    or symbol
                    or (
                        default_element.get("name")
                        if default_element
                        else None
                    )
                    or chunk.file_path
                )

                key = (
                    chosen_symbol.lower(),
                    chunk_file,
                    class_name.lower(),
                )

                if key not in candidates_by_key:
                    candidates_by_key[key] = (
                        _CandidateTarget(
                            symbol_name=chosen_symbol,
                            file_path=chunk.file_path,
                            class_name=class_name or None,
                            primary_chunk=chunk,
                            element=default_element,
                            score=chunk.score,
                            has_symbol_match=False,
                        )
                    )

                else:
                    existing = candidates_by_key[key]

                    if chunk.score > existing.score:
                        existing.primary_chunk = chunk
                        existing.score = chunk.score

        return list(
            candidates_by_key.values()
        )

    @staticmethod
    def _filter_plausible_candidates(
        candidates: list[_CandidateTarget],
    ) -> list[_CandidateTarget]:
        """
        Filter weak candidates for normal non-conflict cases.

        If the same exact symbol exists in multiple files,
        preserve all symbol-matched candidates so that
        _resolve_target() can perform proper disambiguation.
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

        # ---------------------------------------------------------
        # If the same symbol exists across multiple files,
        # preserve every exact symbol candidate.
        # ---------------------------------------------------------
        symbol_files = {
            candidate.file_path.lower()
            for candidate in pool
        }

        if len(symbol_files) > 1:
            return pool

        max_score = max(
            candidate.score
            for candidate in pool
        )

        plausible = []

        for candidate in pool:
            if (
                candidate.score
                >= max_score - 0.20
                or candidate.score
                >= 0.70 * max_score
                or (
                    candidate.has_symbol_match
                    and candidate.score >= 0.30
                )
            ):
                plausible.append(candidate)

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
        Calculate query/context evidence for a candidate.

        Stronger evidence receives higher weight:

        1. Explicit file/path
        2. Class name
        3. File/stem/domain
        4. Explicit symbol
        5. Keyword overlap

        Retrieval score is intentionally NOT included here.
        """

        score = 0.0

        query_lower = (
            context.query or ""
        ).lower()

        # ---------------------------------------------------------
        # Correct identifier/token extraction.
        # ---------------------------------------------------------
        query_tokens = set(
            re.findall(
                r"\b[a-zA-Z_][a-zA-Z0-9_]*\b",
                query_lower,
            )
        )

        ctx_keywords = {
            str(keyword)
            .strip()
            .lower()
            for keyword in (
                context.keywords or []
            )
            if keyword
            and str(keyword).strip()
        }

        ctx_identifiers = {
            str(identifier)
            .strip()
            .lower()
            for identifier in (
                context.identifiers or []
            )
            if identifier
            and str(identifier).strip()
        }

        ctx_file_paths = [
            (
                str(file_path)
                .strip()
                .lower()
                .replace("\\", "/")
            )
            for file_path in (
                context.file_paths or []
            )
            if file_path
            and str(file_path).strip()
        ]

        candidate_file = (
            candidate.file_path
            .lower()
            .replace("\\", "/")
        )

        candidate_filename = (
            candidate_file.split("/")[-1]
        )

        candidate_stem = (
            candidate_filename.rsplit(".", 1)[0]
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
        # 1. EXPLICIT FILE PATH
        # Strongest discriminator.
        # ---------------------------------------------------------
        for file_path in ctx_file_paths:
            if (
                file_path == candidate_file
                or candidate_file.endswith(file_path)
                or file_path in candidate_file
            ):
                score += 20.0
                break

            if (
                candidate_filename == file_path
                or candidate_stem == file_path
            ):
                score += 16.0
                break

        # ---------------------------------------------------------
        # File name/stem mentioned in identifiers/keywords.
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
        # File name/stem directly mentioned in query.
        # ---------------------------------------------------------
        if candidate_filename in query_tokens:
            score += 10.0

        elif (
            candidate_stem in query_tokens
            and len(candidate_stem) > 2
        ):
            score += 8.0

        # ---------------------------------------------------------
        # Directory/domain match.
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
        # 2. CLASS NAME
        # ---------------------------------------------------------
        if candidate_class:
            if candidate_class in ctx_identifiers:
                score += 16.0

            if candidate_class in ctx_keywords:
                score += 10.0

            if candidate_class in query_tokens:
                score += 12.0

            # Handle ProductService vs "product service".
            normalized_class = re.sub(
                r"(?<!^)(?=[A-Z])",
                " ",
                candidate.class_name or "",
            ).lower()

            normalized_class_tokens = set(
                normalized_class.split()
            )

            query_without_punctuation = re.sub(
                r"[^a-z0-9_ ]+",
                " ",
                query_lower,
            )

            if normalized_class in query_without_punctuation:
                score += 10.0

            for class_token in normalized_class_tokens:
                if (
                    len(class_token) > 2
                    and class_token in query_tokens
                ):
                    score += 3.0

        # ---------------------------------------------------------
        # 3. SYMBOL MATCH
        # ---------------------------------------------------------
        if candidate_symbol in ctx_identifiers:
            score += 8.0

        if candidate_symbol in query_tokens:
            score += 6.0

        # ---------------------------------------------------------
        # 4. LLM element file match
        # ---------------------------------------------------------
        if candidate.element:
            element_file = (
                str(
                    candidate.element.get(
                        "file_path"
                    )
                    or ""
                )
                .strip()
                .lower()
                .replace("\\", "/")
            )

            if element_file and (
                element_file == candidate_file
                or candidate_file.endswith(
                    element_file
                )
                or element_file in candidate_file
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
    def _select_best_element(
        chunks: list[RetrievedChunk],
        elements: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Prefer the LLM element whose symbol exactly matches
        function/class metadata in retrieved chunks.
        """

        for element in elements:
            name = str(
                element.get("name", "")
            ).strip().lower()

            if not name:
                continue

            for chunk in chunks:
                metadata = chunk.metadata or {}

                function_name = str(
                    metadata.get(
                        "function_name"
                    )
                    or ""
                ).strip().lower()

                class_name = str(
                    metadata.get("class_name")
                    or ""
                ).strip().lower()

                symbol = str(
                    metadata.get("symbol")
                    or ""
                ).strip().lower()

                if name in {
                    function_name,
                    class_name,
                    symbol,
                }:
                    return element

        return elements[0]


def _fallback_identification(
    query: str,
    chunks: list[RetrievedChunk],
) -> list[dict[str, Any]]:
    """
    Deterministic fallback when LLM code identification fails.
    """

    if not query or not chunks:
        return []

    # Correct identifier regex.
    candidates = re.findall(
        r"\b[A-Za-z_][A-Za-z0-9_]*\b",
        query,
    )

    stop_words = {
        "find",
        "where",
        "is",
        "are",
        "the",
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
    }

    candidates = [
        candidate
        for candidate in candidates
        if candidate.lower()
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

        for candidate in candidates:
            candidate_lower = (
                candidate.lower()
            )

            if (
                function_name.lower()
                == candidate_lower
            ):
                matches.append(
                    {
                        "name": function_name,
                        "file_path": chunk.file_path,
                        "class_name": (
                            class_name or None
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
                        "identification_method": (
                            "deterministic_fallback"
                        ),
                    }
                )
                break

            if (
                class_name.lower()
                == candidate_lower
            ):
                matches.append(
                    {
                        "name": class_name,
                        "file_path": chunk.file_path,
                        "class_name": (
                            class_name or None
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
                        "identification_method": (
                            "deterministic_fallback"
                        ),
                    }
                )
                break

            if (
                symbol.lower()
                == candidate_lower
            ):
                matches.append(
                    {
                        "name": symbol,
                        "file_path": chunk.file_path,
                        "class_name": (
                            class_name or None
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
                        "identification_method": (
                            "deterministic_fallback"
                        ),
                    }
                )
                break

    # ---------------------------------------------------------
    # If no explicit candidate token in query matched metadata symbols,
    # extract code elements directly from retrieved chunks.
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
                    {
                        "name": target_name,
                        "file_path": chunk.file_path,
                        "class_name": cname or None,
                        "start_line": metadata.get("start_line"),
                        "end_line": metadata.get("end_line"),
                        "chunk_type": metadata.get("chunk_type"),
                        "identification_method": "chunk_metadata_fallback",
                    }
                )

    # ---------------------------------------------------------
    # Deduplicate matches.
    # ---------------------------------------------------------
    unique_matches: list[
        dict[str, Any]
    ] = []

    seen: set[
        tuple[str, str]
    ] = set()

    for match in matches:
        key = (
            str(match["name"]).lower(),
            str(match["file_path"]).lower(),
        )

        if key not in seen:
            seen.add(key)
            unique_matches.append(match)

    return unique_matches


def _find_primary_chunk(
    chunks: list[RetrievedChunk],
    element: dict[str, Any],
) -> RetrievedChunk | None:
    """
    Find the primary retrieved chunk for the identified element.

    Priority:

    1. Exact file path + exact function/class/symbol.
    2. Exact file path.
    3. Exact function/class/symbol across chunks.
    4. Highest-scoring retrieved chunk.

    The file-path fallback is important when the identified
    symbol is something inside a function, such as a variable,
    imported class, library call, or API usage.
    """

    if not chunks:
        return None

    name = str(
        element.get("name", "")
    ).strip().lower()

    file_hint = (
        str(
            element.get("file_path", "")
        )
        .strip()
        .lower()
        .replace("\\", "/")
    )

    # ---------------------------------------------------------
    # 1. Exact file + exact function/class/symbol match
    # ---------------------------------------------------------
    if file_hint and name:
        for chunk in chunks:
            chunk_file = (
                str(chunk.file_path or "")
                .strip()
                .lower()
                .replace("\\", "/")
            )

            metadata = chunk.metadata or {}

            function_name = str(
                metadata.get(
                    "function_name"
                )
                or ""
            ).strip().lower()

            class_name = str(
                metadata.get(
                    "class_name"
                )
                or ""
            ).strip().lower()

            symbol = str(
                metadata.get("symbol")
                or ""
            ).strip().lower()

            if (
                chunk_file == file_hint
                and name in {
                    function_name,
                    class_name,
                    symbol,
                }
            ):
                return chunk

    # ---------------------------------------------------------
    # 2. Exact file path match
    # ---------------------------------------------------------
    if file_hint:
        file_matches = [
            chunk
            for chunk in chunks
            if (
                str(chunk.file_path or "")
                .strip()
                .lower()
                .replace("\\", "/")
                == file_hint
            )
        ]

        if file_matches:
            return max(
                file_matches,
                key=lambda chunk: chunk.score,
            )

    # ---------------------------------------------------------
    # 3. Exact function/class/symbol match
    # ---------------------------------------------------------
    if name:
        matches = []

        for chunk in chunks:
            metadata = chunk.metadata or {}

            function_name = str(
                metadata.get(
                    "function_name"
                )
                or ""
            ).strip().lower()

            class_name = str(
                metadata.get(
                    "class_name"
                )
                or ""
            ).strip().lower()

            symbol = str(
                metadata.get("symbol")
                or ""
            ).strip().lower()

            if name in {
                function_name,
                class_name,
                symbol,
            }:
                matches.append(chunk)

        if matches:
            return max(
                matches,
                key=lambda chunk: chunk.score,
            )

    # ---------------------------------------------------------
    # 4. Final fallback:
    # Highest-scoring retrieved chunk.
    # ---------------------------------------------------------
    return max(
        chunks,
        key=lambda chunk: chunk.score,
    )