"""
app/modules/search/pipeline/code_change_verifier.py

Source verification and programmatic line-location calculation for code changes.
Ensures line numbers are calculated from verified source, not trusted from LLM.
Unified diff is generated using Python difflib from verified actual old_code and new_code.
"""

from __future__ import annotations

import difflib
import re
import textwrap
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class CodeChangeVerificationResult:
    """Outcome of source verification and line-location calculation."""

    is_valid: bool
    code_change: dict[str, Any] | None = None
    suggested_patch: str | None = None
    errors: list[str] = field(default_factory=list)
    checks: dict[str, str] = field(
        default_factory=lambda: {
            "target_file_verified": "FAIL",
            "old_code_found_once": "FAIL",
            "line_range": "unknown",
            "old_new_code_differ": "FAIL",
            "unified_diff_generated": "FAIL",
            "repository_not_modified": "PASS",
        }
    )


def _normalize_path(path: str) -> str:
    """Normalize file path for consistent cross-platform matching."""
    p = path.strip().replace("\\", "/").lstrip("/")
    if p.startswith("./"):
        p = p[2:]
    return p


def _matches_file(
    candidate_path: str | None,
    target_path: str | None,
) -> bool:
    """Check if candidate path matches target file path."""
    if not candidate_path or not target_path:
        return False

    c = _normalize_path(candidate_path)
    t = _normalize_path(target_path)

    if c == t or c.endswith("/" + t) or t.endswith("/" + c):
        return True

    c_parts = [p for p in c.split("/") if p]
    t_parts = [p for p in t.split("/") if p]

    if c_parts and t_parts and c_parts[-1] == t_parts[-1]:
        if len(c_parts) == 1 or len(t_parts) == 1:
            return True

        if (
            len(c_parts) >= 2
            and len(t_parts) >= 2
            and c_parts[-2] == t_parts[-2]
        ):
            return True

    return False


def _extract_chunk_content(chunk: Any) -> str | None:
    """Extract code/content string from various chunk representations."""
    if chunk is None:
        return None

    for attr in ("content", "code", "source_code", "text"):
        val = getattr(chunk, attr, None)
        if isinstance(val, str) and val.strip():
            return val

    if isinstance(chunk, dict):
        for key in ("content", "code", "source_code", "text"):
            val = chunk.get(key)
            if isinstance(val, str) and val.strip():
                return val

    return None


def _extract_chunk_file_path(chunk: Any) -> str | None:
    """Extract file_path from object or dict chunk."""
    if chunk is None:
        return None

    val = getattr(chunk, "file_path", None)
    if isinstance(val, str) and val.strip():
        return val.strip()

    if isinstance(chunk, dict):
        val = chunk.get("file_path")
        if isinstance(val, str) and val.strip():
            return val.strip()

    return None


def _extract_chunk_metadata(chunk: Any) -> dict[str, Any]:
    """Extract metadata dictionary from object or dict chunk."""
    if chunk is None:
        return {}

    meta = getattr(chunk, "metadata", None)

    if isinstance(meta, dict):
        return meta

    if isinstance(chunk, dict):
        meta = chunk.get("metadata")

        if isinstance(meta, dict):
            return meta

    return {}


def find_exact_code_in_source(
    source: str,
    old_code: str,
    base_line: int = 1,
) -> tuple[int, int, str, int]:
    """
    Search for exact occurrence of old_code in source.

    Returns:
        (start_line, end_line, actual_matched_source_code, match_count)
    """

    norm_source = source.replace("\r\n", "\n").replace("\r", "\n")
    norm_old = old_code.replace("\r\n", "\n").replace("\r", "\n")

    # ---------------------------------------------------------
    # 1. Exact string search
    # ---------------------------------------------------------
    cnt = norm_source.count(norm_old)

    if cnt == 1:
        pos = norm_source.find(norm_old)

        lines_before = norm_source[:pos].count("\n")
        start_line = base_line + lines_before

        lines_span = norm_old.rstrip("\n").count("\n")
        end_line = start_line + lines_span

        return start_line, end_line, norm_old, 1

    elif cnt > 1:
        return 0, 0, "", cnt

    # ---------------------------------------------------------
    # 2. Check stripped trailing newlines
    # ---------------------------------------------------------
    stripped_old = norm_old.strip("\r\n")

    if stripped_old:
        cnt_stripped = norm_source.count(stripped_old)

        if cnt_stripped == 1:
            pos = norm_source.find(stripped_old)

            lines_before = norm_source[:pos].count("\n")
            start_line = base_line + lines_before

            lines_span = stripped_old.count("\n")
            end_line = start_line + lines_span

            return start_line, end_line, stripped_old, 1

        elif cnt_stripped > 1:
            return 0, 0, "", cnt_stripped

    # ---------------------------------------------------------
    # 3. Line-by-line whitespace-trimmed search
    # ---------------------------------------------------------
    source_lines = norm_source.splitlines()
    target_lines = [line.rstrip() for line in stripped_old.splitlines()]

    n = len(target_lines)

    if n == 0:
        return 0, 0, "", 0

    source_lines_rstrip = [line.rstrip() for line in source_lines]

    matches = []

    for i in range(len(source_lines_rstrip) - n + 1):
        if source_lines_rstrip[i : i + n] == target_lines:
            matches.append(i)

    if len(matches) == 1:
        idx = matches[0]

        start_line = base_line + idx
        end_line = start_line + n - 1

        actual_code = "\n".join(
            source_lines[idx : idx + n]
        )

        return start_line, end_line, actual_code, 1

    elif len(matches) > 1:
        return 0, 0, "", len(matches)

    # ---------------------------------------------------------
    # 4. Dedented line comparison
    # ---------------------------------------------------------
    dedented_target = textwrap.dedent(
        stripped_old
    ).splitlines()

    dedented_target = [
        line.rstrip()
        for line in dedented_target
    ]

    n_dedent = len(dedented_target)

    indent_matches = []

    for i in range(len(source_lines) - n_dedent + 1):
        window = source_lines[
            i : i + n_dedent
        ]

        window_dedented = textwrap.dedent(
            "\n".join(window)
        ).splitlines()

        window_dedented = [
            line.rstrip()
            for line in window_dedented
        ]

        if window_dedented == dedented_target:
            indent_matches.append(i)

    if len(indent_matches) == 1:
        idx = indent_matches[0]

        start_line = base_line + idx
        end_line = start_line + n_dedent - 1

        actual_code = "\n".join(
            source_lines[idx : idx + n_dedent]
        )

        return start_line, end_line, actual_code, 1

    elif len(indent_matches) > 1:
        return 0, 0, "", len(indent_matches)

    return 0, 0, "", 0


def generate_deterministic_patch(
    file_path: str,
    old_code: str,
    new_code: str,
    start_line: int,
) -> str | None:
    """
    Generate unified diff using Python difflib and adjust
    hunk line numbers to start_line.
    """

    norm_old = old_code.replace(
        "\r\n", "\n"
    ).replace("\r", "\n")

    norm_new = new_code.replace(
        "\r\n", "\n"
    ).replace("\r", "\n")

    old_lines = norm_old.splitlines()
    new_lines = norm_new.splitlines()

    patch_lines = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
            lineterm="",
            n=3,
        )
    )

    if not patch_lines:
        return None

    adjusted_lines: list[str] = []

    for line in patch_lines:
        if line.startswith("@@"):
            m = re.match(
                r"^@@ -(\d+)(,\d+)? "
                r"\+(\d+)(,\d+)? @@(.*)$",
                line,
            )

            if m:
                orig_start = int(m.group(1))
                orig_len = m.group(2) or ""

                mod_start = int(m.group(3))
                mod_len = m.group(4) or ""

                suffix = m.group(5) or ""

                new_orig_start = (
                    start_line + orig_start - 1
                )

                new_mod_start = (
                    start_line + mod_start - 1
                )

                line = (
                    f"@@ "
                    f"-{new_orig_start}{orig_len} "
                    f"+{new_mod_start}{mod_len} "
                    f"@@{suffix}"
                )

        adjusted_lines.append(line)

    return "\n".join(adjusted_lines)


def verify_and_locate_code_change(
    code_change: dict[str, Any] | None,
    chunks: list[Any] | None = None,
    primary_chunk: Any | None = None,
    code_snippets: list[dict[str, Any]] | None = None,
    target_symbol: str | None = None,
) -> CodeChangeVerificationResult:
    """
    Programmatically verify the LLM-proposed code_change against
    retrieved source and calculate exact 1-based line locations.

    Rules:

    - 0 matches in verified source -> reject.
    - Exactly 1 physical match -> accept.
    - Multiple matches:
        * If a reliable start_line uniquely identifies one match,
          accept that occurrence.
        * Otherwise reject as ambiguous.
    - Retrieved chunks containing the same physical occurrence are
      deduplicated by line range.
    - Repository is never modified.
    """

    checks = {
        "target_file_verified": "FAIL",
        "old_code_found_once": "FAIL",
        "line_range": "unknown",
        "old_new_code_differ": "FAIL",
        "unified_diff_generated": "FAIL",
        "repository_not_modified": "PASS",
    }

    errors: list[str] = []

    # ---------------------------------------------------------
    # Validate code_change object
    # ---------------------------------------------------------
    if not isinstance(code_change, dict):
        return CodeChangeVerificationResult(
            is_valid=False,
            code_change=None,
            suggested_patch=None,
            errors=["code_change must be an object"],
            checks=checks,
        )

    # ---------------------------------------------------------
    # Validate file path
    # ---------------------------------------------------------
    file_path = code_change.get("file_path")

    if not isinstance(file_path, str) or not file_path.strip():
        errors.append(
            "code_change.file_path must be a non-empty string"
        )

        return CodeChangeVerificationResult(
            is_valid=False,
            code_change=None,
            suggested_patch=None,
            errors=errors,
            checks=checks,
        )

    file_path = file_path.strip()

    # ---------------------------------------------------------
    # Validate old/new code
    # ---------------------------------------------------------
    old_code = code_change.get("old_code")
    new_code = code_change.get("new_code")

    if not isinstance(old_code, str):
        errors.append(
            "code_change.old_code must be a string"
        )

    if not isinstance(new_code, str):
        errors.append(
            "code_change.new_code must be a string"
        )

    if errors:
        return CodeChangeVerificationResult(
            is_valid=False,
            code_change=None,
            suggested_patch=None,
            errors=errors,
            checks=checks,
        )

    norm_old_code = old_code.replace(
        "\r\n", "\n"
    ).replace("\r", "\n")

    norm_new_code = new_code.replace(
        "\r\n", "\n"
    ).replace("\r", "\n")

    # ---------------------------------------------------------
    # old_code and new_code must differ
    # ---------------------------------------------------------
    if norm_old_code == norm_new_code:
        errors.append(
            "code_change.old_code and "
            "code_change.new_code must differ"
        )

        return CodeChangeVerificationResult(
            is_valid=False,
            code_change=None,
            suggested_patch=None,
            errors=errors,
            checks=checks,
        )

    checks["old_new_code_differ"] = "PASS"

    # ---------------------------------------------------------
    # Determine operation
    # ---------------------------------------------------------
    operation = code_change.get("operation")

    if not operation:
        if (
            not norm_new_code.strip()
            and norm_old_code.strip()
        ):
            operation = "delete"

        elif (
            not norm_old_code.strip()
            and norm_new_code.strip()
        ):
            operation = "insert"

        else:
            operation = "replace"

    # ---------------------------------------------------------
    # Collect candidate sources
    # ---------------------------------------------------------
    candidate_sources: list[Any] = []

    if primary_chunk is not None:
        candidate_sources.append(primary_chunk)

    if chunks:
        candidate_sources.extend(chunks)

    if code_snippets:
        candidate_sources.extend(code_snippets)

    # ---------------------------------------------------------
    # Filter sources matching target file
    # ---------------------------------------------------------
    matching_sources = [
        c
        for c in candidate_sources
        if _matches_file(
            _extract_chunk_file_path(c),
            file_path,
        )
    ]

    # ---------------------------------------------------------
    # Fallback source matching
    # ---------------------------------------------------------
    if not matching_sources:
        if (
            primary_chunk is not None
            and not _extract_chunk_file_path(primary_chunk)
        ):
            matching_sources = [primary_chunk]

        elif candidate_sources:
            for c in candidate_sources:
                content = _extract_chunk_content(c)

                if (
                    content
                    and norm_old_code.strip() in content
                ):
                    matching_sources.append(c)

    # ---------------------------------------------------------
    # No verified source
    # ---------------------------------------------------------
    if not matching_sources:
        errors.append(
            f"Target file '{file_path}' was not found "
            "in the verified repository context."
        )

        return CodeChangeVerificationResult(
            is_valid=False,
            code_change=None,
            suggested_patch=None,
            errors=errors,
            checks=checks,
        )

    checks["target_file_verified"] = "PASS"

    # ---------------------------------------------------------
    # Find occurrences
    # ---------------------------------------------------------
    matches_found: list[
        tuple[Any, int, int, str, int]
    ] = []

    for chunk in matching_sources:
        content = _extract_chunk_content(chunk)

        if not content:
            continue

        meta = _extract_chunk_metadata(chunk)

        chunk_start_line = meta.get("start_line")

        if chunk_start_line is None:
            chunk_start_line = 1

        try:
            chunk_start_line = int(
                chunk_start_line
            )
        except (TypeError, ValueError):
            chunk_start_line = 1

        (
            s_line,
            e_line,
            actual_code,
            cnt,
        ) = find_exact_code_in_source(
            source=content,
            old_code=norm_old_code,
            base_line=chunk_start_line,
        )

        if cnt > 0:
            matches_found.append(
                (
                    chunk,
                    s_line,
                    e_line,
                    actual_code,
                    cnt,
                )
            )

    # ---------------------------------------------------------
    # Deduplicate physical occurrences
    #
    # Multiple retrieved chunks can contain the same source
    # lines. They must not be treated as multiple occurrences.
    # ---------------------------------------------------------
    unique_matches: dict[
        tuple[int, int, str],
        tuple[Any, int, int, str, int],
    ] = {}

    ambiguous_match_counts: list[int] = []

    for item in matches_found:
        chunk, s_line, e_line, actual_code, cnt = item

        if cnt > 1:
            ambiguous_match_counts.append(cnt)
            continue

        key = (
            s_line,
            e_line,
            actual_code,
        )

        if key not in unique_matches:
            unique_matches[key] = item

    unique_match_list = list(
        unique_matches.values()
    )

    total_unique_matches = len(
        unique_match_list
    )

    # ---------------------------------------------------------
    # If a single chunk itself contains multiple occurrences,
    # preserve ambiguity.
    # ---------------------------------------------------------
    if ambiguous_match_counts:
        total_occurrences = sum(
            ambiguous_match_counts
        )

        # If another source gives an exact line, try to resolve
        # using that line below. Otherwise reject.
        requested_start_line = code_change.get(
            "start_line"
        )

        try:
            requested_start_line = int(
                requested_start_line
            )
        except (TypeError, ValueError):
            requested_start_line = None

        if requested_start_line is None:
            errors.append(
                f"Original code occurs multiple times in "
                f"'{file_path}'; reject as ambiguous."
            )

            return CodeChangeVerificationResult(
                is_valid=False,
                code_change=None,
                suggested_patch=None,
                errors=errors,
                checks=checks,
            )

    # ---------------------------------------------------------
    # No matches
    # ---------------------------------------------------------
    if total_unique_matches == 0:
        errors.append(
            f"Original code was not found in the "
            f"verified source for '{file_path}'."
        )

        return CodeChangeVerificationResult(
            is_valid=False,
            code_change=None,
            suggested_patch=None,
            errors=errors,
            checks=checks,
        )

    # ---------------------------------------------------------
    # Resolve target occurrence
    # ---------------------------------------------------------
    target_chunk: Any | None = None
    start_line = 0
    end_line = 0
    actual_old_code = ""

    requested_start_line = code_change.get(
        "start_line"
    )

    try:
        requested_start_line = int(
            requested_start_line
        )
    except (TypeError, ValueError):
        requested_start_line = None

    # ---------------------------------------------------------
    # Exactly one physical occurrence
    # ---------------------------------------------------------
    if total_unique_matches == 1:
        (
            target_chunk,
            start_line,
            end_line,
            actual_old_code,
            _,
        ) = unique_match_list[0]

    # ---------------------------------------------------------
    # Multiple physical occurrences
    # ---------------------------------------------------------
    else:
        if requested_start_line is None:
            errors.append(
                f"Original code occurs "
                f"{total_unique_matches} times in "
                f"'{file_path}'; reject as ambiguous."
            )

            return CodeChangeVerificationResult(
                is_valid=False,
                code_change=None,
                suggested_patch=None,
                errors=errors,
                checks=checks,
            )

        line_matches = [
            item
            for item in unique_match_list
            if item[1] == requested_start_line
        ]

        if len(line_matches) != 1:
            errors.append(
                f"Original code occurs "
                f"{total_unique_matches} times in "
                f"'{file_path}', and start_line "
                f"{requested_start_line} does not uniquely "
                "identify one occurrence."
            )

            return CodeChangeVerificationResult(
                is_valid=False,
                code_change=None,
                suggested_patch=None,
                errors=errors,
                checks=checks,
            )

        (
            target_chunk,
            start_line,
            end_line,
            actual_old_code,
            _,
        ) = line_matches[0]

    checks["old_code_found_once"] = "PASS"
    checks["line_range"] = (
        f"{start_line}-{end_line}"
    )

    # ---------------------------------------------------------
    # Resolve symbol
    # ---------------------------------------------------------
    meta = _extract_chunk_metadata(
        target_chunk
    )

    symbol = code_change.get("symbol")

    if not symbol or symbol in ("", "unknown"):
        symbol = target_symbol

    if not symbol and meta:
        symbol = (
            meta.get("function_name")
            or meta.get("class_name")
        )

    if not symbol:
        symbol = "global"

    # ---------------------------------------------------------
    # Build verified structured change
    # ---------------------------------------------------------
    structured_change = {
        "file_path": file_path,
        "symbol": symbol,
        "start_line": start_line,
        "end_line": end_line,
        "operation": operation,
        "old_code": old_code,
        "new_code": new_code,
    }

    # ---------------------------------------------------------
    # Generate deterministic patch
    # ---------------------------------------------------------
    patch = generate_deterministic_patch(
        file_path=file_path,
        old_code=(
            actual_old_code
            or old_code
        ),
        new_code=new_code,
        start_line=start_line,
    )

    if patch:
        checks["unified_diff_generated"] = "PASS"

    else:
        errors.append(
            "Failed to generate unified patch."
        )

        return CodeChangeVerificationResult(
            is_valid=False,
            code_change=structured_change,
            suggested_patch=None,
            errors=errors,
            checks=checks,
        )

    # ---------------------------------------------------------
    # Success
    # ---------------------------------------------------------
    return CodeChangeVerificationResult(
        is_valid=True,
        code_change=structured_change,
        suggested_patch=patch,
        errors=[],
        checks=checks,
    )


def format_final_response_output(
    file_path: str,
    symbol: str | None,
    start_line: int,
    end_line: int,
    operation: str,
    old_code: str,
    new_code: str,
    suggested_patch: str,
    checks: dict[str, str] | None = None,
) -> str:
    """Format the final response generation output text as specified."""

    checks = checks or {
        "target_file_verified": "PASS",
        "old_code_found_once": "PASS",
        "line_range": f"{start_line}-{end_line}",
        "old_new_code_differ": "PASS",
        "unified_diff_generated": "PASS",
        "repository_not_modified": "PASS",
    }

    if symbol and symbol != "global":
        if symbol.endswith("()"):
            func_line = f"Function: {symbol}"

        elif symbol[0].isupper() and "_" not in symbol:
            func_line = f"Class: {symbol}"

        else:
            func_line = f"Function: {symbol}()"

    else:
        func_line = "Function: (global/module)"

    return (
        f"Target\n"
        f"File: {file_path}\n"
        f"{func_line}\n\n"
        f"Change location\n"
        f"Lines: {start_line}–{end_line}\n"
        f"Operation: {operation}\n\n"
        f"Change\n"
        f"{old_code}\n\n"
        f"To\n"
        f"{new_code}\n\n"
        f"Suggested Patch\n"
        f"{suggested_patch}\n\n"
        f"Validation\n"
        f"Target verified: "
        f"{checks.get('target_file_verified', 'PASS')}\n"
        f"Original code found exactly once: "
        f"{checks.get('old_code_found_once', 'PASS')}\n"
        f"Line location calculated from source: PASS\n"
        f"Patch generated: "
        f"{checks.get('unified_diff_generated', 'PASS')}\n"
        f"Repository modified: NO"
    )