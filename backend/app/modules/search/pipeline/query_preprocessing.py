
"""
app/modules/search/pipeline/query_preprocessing.py

Pipeline stage: Query preprocessing / structured query understanding.

Extracts structured information from the user's query after intent
classification.

Normal path:
    LLMService -> structured query information

Fallback path:
    LLM failure / unavailable intent -> deterministic code extraction

The fallback is intentionally conservative and does not invent
repository, language, file, or symbol information.
"""

from __future__ import annotations

import re

from app.core.logging import get_logger
from app.modules.llm.service.llm_service import LLMService
from app.modules.search.domain.search_domain import SearchContext

logger = get_logger(__name__)


class QueryPreprocessingStage:
    """Pipeline stage responsible for structured query preprocessing."""

    def __init__(self, llm_service: LLMService) -> None:
        self.llm_service = llm_service

    async def execute(self, context: SearchContext) -> None:
        """
        Extract structured query information.

        Normal flow:
            LLMService -> validated result -> SearchContext

        Fallback flow:
            LLM failure / unavailable intent
            -> deterministic extraction
            -> SearchContext
            -> continue pipeline

        The fallback never attempts semantic interpretation that
        requires an LLM.
        """

        # -----------------------------------------------------------
        # Respect an early exit produced by an earlier pipeline stage.
        # -----------------------------------------------------------
        if context.early_exit:
            logger.info(
                "query_preprocessing_skipped",
                reason=context.early_exit,
                repo_id=context.repo_id,
            )
            return

        # -----------------------------------------------------------
        # Query validation
        #
        # An empty query is a genuine invalid request and should
        # remain an error. This is not an LLM failure.
        # -----------------------------------------------------------
        if not context.query or not context.query.strip():
            raise ValueError(
                "Cannot preprocess an empty query."
            )

        query = context.query.strip()

        logger.info(
            "query_preprocessing_starting",
            repo_id=context.repo_id,
            intent=(
                context.intent.value
                if context.intent is not None
                else None
            ),
        )

        # -----------------------------------------------------------
        # If intent classification was unavailable, do not stop the
        # pipeline. Use deterministic preprocessing directly.
        #
        # This is important because raising here would defeat the
        # fallback added to IntentClassificationStage.
        # -----------------------------------------------------------
        if context.intent is None:
            logger.warning(
                "query_preprocessing_missing_intent_using_code_fallback",
                repo_id=context.repo_id,
            )

            self._apply_fallback(context)

            return

        # -----------------------------------------------------------
        # Primary path: LLM preprocessing
        # -----------------------------------------------------------
        try:
            result = await self.llm_service.preprocess_query(
                query=query,
                intent=context.intent,
                parameters=context.intent_parameters,
            )

        except Exception as exc:
            logger.warning(
                "query_preprocessing_llm_failed_using_code_fallback",
                repo_id=context.repo_id,
                error=str(exc),
            )

            self._apply_fallback(context)

            return

        # -----------------------------------------------------------
        # Validate LLM result
        # -----------------------------------------------------------
        if not isinstance(result, dict):
            logger.warning(
                "query_preprocessing_invalid_llm_result_using_code_fallback",
                repo_id=context.repo_id,
            )

            self._apply_fallback(context)

            return

        # -----------------------------------------------------------
        # Preserve existing successful LLM behavior.
        #
        # Only assign the fields that already belong to SearchContext.
        # -----------------------------------------------------------
        context.keywords = self._normalize_string_list(
            result.get("keywords", [])
        )

        context.identifiers = self._normalize_string_list(
            result.get("identifiers", [])
        )

        context.file_paths = self._normalize_string_list(
            result.get("file_paths", [])
        )

        context.repo_hint = self._normalize_optional_string(
            result.get("repo_hint")
        )

        context.language_hint = self._normalize_optional_string(
            result.get("language_hint")
        )

        logger.info(
            "query_preprocessing_complete",
            repo_id=context.repo_id,
            keywords=context.keywords,
            identifiers=context.identifiers,
            file_paths=context.file_paths,
            repo_hint=context.repo_hint,
            language_hint=context.language_hint,
            fallback_used=False,
        )

    # ----------------------------------------------------------------
    # Deterministic fallback
    # ----------------------------------------------------------------
    def _apply_fallback(self, context: SearchContext) -> None:
        """
        Apply deterministic query preprocessing.

        This method does not use an LLM.

        It extracts only information that can be reasonably identified
        from the raw query using deterministic rules.
        """

        query = context.query.strip()

        keywords = self._extract_keywords(query)
        identifiers = self._extract_identifiers(query)
        file_paths = self._extract_file_paths(query)

        # -----------------------------------------------------------
        # Do not infer repository or language unless explicitly
        # recognizable from the query.
        # -----------------------------------------------------------
        repo_hint = self._extract_repository_hint(query)
        language_hint = self._extract_language_hint(query)

        context.keywords = keywords
        context.identifiers = identifiers
        context.file_paths = file_paths
        context.repo_hint = repo_hint
        context.language_hint = language_hint

        logger.info(
            "query_preprocessing_code_fallback_complete",
            repo_id=context.repo_id,
            keywords=context.keywords,
            identifiers=context.identifiers,
            file_paths=context.file_paths,
            repo_hint=context.repo_hint,
            language_hint=context.language_hint,
            fallback_used=True,
        )

    # ----------------------------------------------------------------
    # Keyword extraction
    # ----------------------------------------------------------------
    @staticmethod
    def _extract_keywords(query: str) -> list[str]:
        """
        Extract useful lexical terms from the query.

        This is deliberately simple. It is not intended to replace
        semantic query understanding.
        """

        words = re.findall(
            r"\b[A-Za-z_][A-Za-z0-9_]*\b",
            query,
        )

        stop_words = {
            "a",
            "an",
            "and",
            "are",
            "as",
            "at",
            "be",
            "by",
            "can",
            "code",
            "do",
            "does",
            "for",
            "from",
            "get",
            "give",
            "how",
            "i",
            "in",
            "into",
            "is",
            "it",
            "me",
            "method",
            "of",
            "on",
            "please",
            "show",
            "that",
            "the",
            "this",
            "to",
            "what",
            "where",
            "which",
            "with",
        }

        keywords: list[str] = []
        seen: set[str] = set()

        for word in words:
            normalized = word.lower()

            if normalized in stop_words:
                continue

            if len(normalized) < 2:
                continue

            if normalized not in seen:
                seen.add(normalized)
                keywords.append(word)

        # Keep the fallback bounded so retrieval does not receive
        # an unnecessarily large query expansion.
        return keywords[:10]

    # ----------------------------------------------------------------
    # Identifier extraction
    # ----------------------------------------------------------------
    @staticmethod
    def _extract_identifiers(query: str) -> list[str]:
        """
        Extract likely code identifiers.

        Supports common:
            camelCase
            PascalCase
            snake_case
            SCREAMING_SNAKE_CASE

        Natural-language words are filtered conservatively.
        """

        candidates = re.findall(
            r"\b[A-Za-z_][A-Za-z0-9_]*\b",
            query,
        )

        identifiers: list[str] = []
        seen: set[str] = set()

        for value in candidates:
            # camelCase / PascalCase
            has_camel_case = bool(
                re.search(r"[a-z][A-Z]", value)
            )

            # snake_case
            has_underscore = "_" in value and not value.startswith("_")

            # Contains a digit while looking identifier-like
            has_identifier_digit = (
                bool(re.search(r"[A-Za-z]", value))
                and bool(re.search(r"\d", value))
            )

            # PascalCase with multiple words
            has_pascal_case = bool(
                re.match(r"^[A-Z][a-z]+(?:[A-Z][A-Za-z0-9]*)+$", value)
            )

            if not (
                has_camel_case
                or has_underscore
                or has_identifier_digit
                or has_pascal_case
            ):
                continue

            normalized = value.lower()

            if normalized in seen:
                continue

            seen.add(normalized)
            identifiers.append(value)

        return identifiers[:10]

    # ----------------------------------------------------------------
    # File-path extraction
    # ----------------------------------------------------------------
    @staticmethod
    def _extract_file_paths(query: str) -> list[str]:
        """
        Extract explicit file paths or filenames from the query.

        Only returns paths that contain a recognized source/config
        file extension. It does not invent paths.
        """

        extension_pattern = (
            r"(?:"
            r"py|js|jsx|ts|tsx|java|kt|kts|go|rs|cpp|cc|cxx|c|h|hpp|"
            r"cs|php|rb|swift|scala|sql|html|css|scss|sass|vue|svelte|"
            r"json|yaml|yml|xml|toml|ini|env"
            r")"
        )

        pattern = rf"""
            (?<![\w.-])
            (?:
                [A-Za-z0-9_.-]+/
            )*
            [A-Za-z0-9_.-]+\.
            {extension_pattern}
            (?![\w.-])
        """

        matches = re.findall(
            pattern,
            query,
            flags=re.IGNORECASE | re.VERBOSE,
        )

        paths: list[str] = []
        seen: set[str] = set()

        for value in matches:
            normalized = value.lower()

            if normalized in seen:
                continue

            seen.add(normalized)
            paths.append(value)

        return paths[:10]

    # ----------------------------------------------------------------
    # Repository hint extraction
    # ----------------------------------------------------------------
    @staticmethod
    def _extract_repository_hint(
        query: str,
    ) -> str | None:
        """
        Extract an explicitly mentioned repository hint.

        This method is intentionally conservative.

        Examples:
            repository demo1_enrollment
            repo demo1_enrollment

        No repository is inferred from unrelated words.
        """

        pattern = re.compile(
            r"\b(?:repository|repo)\s*[:=]?\s*"
            r"([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?)\b",
            flags=re.IGNORECASE,
        )

        match = pattern.search(query)

        if not match:
            return None

        return match.group(1)

    # ----------------------------------------------------------------
    # Language hint extraction
    # ----------------------------------------------------------------
    @staticmethod
    def _extract_language_hint(
        query: str,
    ) -> str | None:
        """
        Extract an explicitly mentioned programming language.
        """

        language_aliases = {
            "python": "python",
            "py": "python",
            "javascript": "javascript",
            "js": "javascript",
            "typescript": "typescript",
            "ts": "typescript",
            "java": "java",
            "kotlin": "kotlin",
            "go": "go",
            "golang": "go",
            "rust": "rust",
            "c++": "cpp",
            "cpp": "cpp",
            "c#": "csharp",
            "csharp": "csharp",
            "php": "php",
            "ruby": "ruby",
            "swift": "swift",
            "scala": "scala",
        }

        normalized_query = query.lower()

        # Check longer/more specific names first.
        for alias, language in sorted(
            language_aliases.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            if re.search(
                rf"(?<![a-z0-9+#]){re.escape(alias)}(?![a-z0-9+#])",
                normalized_query,
            ):
                return language

        return None

    # ----------------------------------------------------------------
    # Result normalization helpers
    # ----------------------------------------------------------------
    @staticmethod
    def _normalize_string_list(
        value: object,
    ) -> list[str]:
        """
        Normalize a list-like LLM field without inventing values.

        Invalid values become an empty list rather than stopping the
        search pipeline.
        """

        if not isinstance(value, list):
            return []

        result: list[str] = []
        seen: set[str] = set()

        for item in value:
            if not isinstance(item, str):
                continue

            cleaned = item.strip()

            if not cleaned:
                continue

            normalized = cleaned.lower()

            if normalized in seen:
                continue

            seen.add(normalized)
            result.append(cleaned)

        return result

    @staticmethod
    def _normalize_optional_string(
        value: object,
    ) -> str | None:
        """
        Normalize an optional string field.
        """

        if not isinstance(value, str):
            return None

        value = value.strip()

        return value or None

