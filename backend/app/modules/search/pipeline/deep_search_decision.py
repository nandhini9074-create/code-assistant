
"""
app/modules/search/pipeline/deep_search_decision.py

Deterministic routing decisions for the optional FIX_BUG Deep Search workflow.

Initial routing:
- Runs before normal retrieval.
- Selects Deep Search for recognized attribute errors, cross-file issues,
  cross-component mismatches, page-level errors, or explicit requests.

Escalation:
- Allows normal FIX_BUG analysis to escalate when evidence is insufficient,
  ambiguous, unavailable, or indicates a potential contract mismatch.

Does not change the FIX_BUG intent or other intents.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from typing import Any


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeepSearchDecision:
    """Result of a Deep Search routing decision."""

    selected: bool
    reason: str


# Explicit requests to trace behavior across files or dependencies.
_CROSS_FILE_PATTERNS = (
    r"\bacross\s+(?:multiple\s+)?files?\b",
    r"\bmultiple\s+files?\b",
    r"\bother\s+files?\b",
    r"\btrace\s+(?:the\s+)?(?:call|data|execution)\s+flow\b",
    r"\btrace\s+(?:this|the)\s+bug\b",
    r"\broot\s+cause\s+across\b",
    r"\bend[- ]to[- ]end\s+(?:flow|execution|trace)\b",
    r"\bdependency\s+(?:chain|graph|analysis|tracing)\b",
    r"\bwhich\s+files?\s+(?:cause|contribute|affect|are\s+involved)\b",
    r"\bfind\s+(?:where|which\s+file)\b.*?\b(?:called|defined|used|passed)\b",
    r"\bfrontend\b.*?\bbackend\b",
    r"\bbackend\b.*?\bfrontend\b",
    r"\broute\b.*?\bservice\b.*?\bmodel\b",
    r"\btemplate\b.*?\bmodel\b",
    r"\bmodel\b.*?\btemplate\b",
    r"\btemplate\b.*?\broute\b",
    r"\broute\b.*?\btemplate\b",
    r"\broute\b.*?\bmodel\b",
    r"\bmodel\b.*?\broute\b",
)

# Signals suggesting a bug involving contracts between components.
_CROSS_COMPONENT_PATTERNS = (
    r"\b(?:attribute|attribut|atribute|attr)\b.{0,40}\bno\b.{0,30}\b(?:object|attribute|field|property)\b",
    r"\bmissing\s+(?:field|attribute|property)\b",
    r"\bundefined\s+(?:field|attribute|property|variable)\b",
    r"\bdoes\s+not\s+exist\s+on\b",
    r"\bnot\s+defined\s+in\b",
    r"\bpassed\s+from\b",
    r"\breturned\s+by\b",
    r"\bconsumed\s+by\b",
    r"\bdata\s+flow\b",
    r"\bcall\s+chain\b",
    r"\bcaller\b.*?\bcallee\b",
    r"\bcallee\b.*?\bcaller\b",
    r"\bmultiple\s+possible\s+locations\b",
    r"\bambiguous\s+(?:function|method|symbol|file|implementation)\b",
    r"\b(?:schema|dto|serializer)\b.*?\b(?:model|database|template)\b",
    r"\b(?:model|database|template)\b.*?\b(?:schema|dto|serializer)\b",
    r"\b(?:template|router|route|crud|schema|model)\b.*?"
    r"\b(?:field|attribute|mapping|contract)\s+mismatch\b",
)

# Runtime errors associated with attribute or field mismatches.
_ATTRIBUTE_ERROR_PATTERNS = (
    # Example: 'Appointment' object has no attribute 'appointment_date'
    r"""['"]?[\w.]+['"]?\s+object\s+has\s+no\s+"""
    r"""(?:attribute|field|property)\s+['"]?[\w.]+['"]?""",

    # Example: appointment has no attribute appointment_date
    r"\b[\w.]+\s+has\s+no\s+(?:attribute|field|property)\s+"
    r"""['"]?[\w.]+['"]?""",

    r"\bhas\s+no\s+(?:attribute|field|property)\b",
    r"\b(?:attributeerror|undefinederror)\b",
    r"\b(?:cannot|could\s+not)\s+access\s+(?:attribute|field|property)\b",
    r"\bno\s+such\s+(?:attribute|field|property)\b",
    r"\bobject\s+has\s+no\b",
    r"\b(?:missing|undefined)\s+attribute\b",
    r"\b(?:attribute|field|property)\s+"
    r"(?:error|does\s+not\s+exist|not\s+found|is\s+missing)\b",
)

# Page-level errors may require tracing templates, handlers, and models.
_PAGE_ERROR_PATTERNS = (
    r"\b(?:page|screen|view|dashboard)\s+"
    r"(?:error|crash|broken|fails?|issue)\b",
    r"\b\w+\s+page\s+(?:returns?|shows?|displays?|throws?|gives?)\s+"
    r"(?:an?\s+)?error\b",
    r"\berror\s+(?:on|in)\s+(?:the\s+)?\w+\s+"
    r"(?:page|view|screen|form|template)\b",
    r"\b\w+\s+page\s+"
    r"(?:not\s+working|is\s+broken|doesn['’]?t\s+work|won['’]?t\s+load)\b",
    r"\bfix\s+(?:the\s+)?\w+\s+page\s+(?:error|issue|bug)\b",
    r"\bfix\s+(?:the\s+)?(?:page|screen|view|dashboard)\s+"
    r"(?:error|issue|bug)\b",
)

# Explicit requests for deeper investigation.
_EXPLICIT_DEEP_SEARCH_PATTERNS = (
    r"\bdeep\s+search\b",
    r"\bdeeply\s+investigate\b",
    r"\binvestigate\s+across\s+files\b",
    r"\btrace\s+the\s+full\s+flow\b",
    r"\bperform\s+(?:a\s+)?root[- ]cause\s+analysis\b",
    r"\b(?:investigate|trace|analyze|analyse)\b.*?"
    r"\b(?:dependencies|dependency\s+chain|related\s+files|root\s+cause)\b",
)


def decide_deep_search(
    *,
    intent: str,
    query: str,
) -> DeepSearchDecision:
    """
    Decide whether a request should use Deep Search before normal retrieval.

    Only FIX_BUG requests are eligible. Routing signals request deeper
    investigation; they do not establish that a particular defect exists.
    """
    normalized_intent = str(intent or "").strip().upper()
    normalized_query = str(query or "").strip()

    logger.debug(
        "deep_search_initial_decision_started",
        extra={
            "intent": normalized_intent,
            "query_length": len(normalized_query),
        },
    )

    if normalized_intent != "FIX_BUG":
        return _decision(
            selected=False,
            reason="Intent is not FIX_BUG; preserve the existing flow.",
            event="deep_search_initial_decision_skipped",
            category="ineligible_intent",
            intent=normalized_intent,
        )

    if not normalized_query:
        return _decision(
            selected=False,
            reason="Query is empty; use the existing pipeline behavior.",
            event="deep_search_initial_decision_skipped",
            category="empty_query",
            intent=normalized_intent,
        )

    pattern_groups = (
        ("explicit_request", _EXPLICIT_DEEP_SEARCH_PATTERNS),
        ("attribute_error", _ATTRIBUTE_ERROR_PATTERNS),
        ("cross_file", _CROSS_FILE_PATTERNS),
        ("cross_component", _CROSS_COMPONENT_PATTERNS),
        ("page_error", _PAGE_ERROR_PATTERNS),
    )

    reasons = {
        "explicit_request": (
            "The user explicitly requested deeper investigation."
        ),
        "attribute_error": (
            "The query contains an attribute or field error that may require "
            "cross-file dependency and field-mapping investigation."
        ),
        "cross_file": (
            "The query requests cross-file or dependency tracing."
        ),
        "cross_component": (
            "The query suggests a cross-component bug investigation."
        ),
        "page_error": (
            "The query describes a page-level error that may require "
            "investigating its template, handler, and data dependencies."
        ),
    }

    for category, patterns in pattern_groups:
        matched_pattern = _find_matching_pattern(normalized_query, patterns)

        if matched_pattern is not None:
            logger.debug(
                "deep_search_pattern_matched",
                extra={
                    "category": category,
                    "pattern": matched_pattern,
                },
            )

            return _decision(
                selected=True,
                reason=reasons[category],
                event="deep_search_initial_decision_selected",
                category=category,
                intent=normalized_intent,
            )

    return _decision(
        selected=False,
        reason="No recognized deep-investigation signal; use the normal flow.",
        event="deep_search_initial_decision_skipped",
        category="no_matching_signal",
        intent=normalized_intent,
    )


def decide_deep_search_escalation(
    *,
    query: str,
    retrieved_chunks: list,
    analysis_result: dict[str, Any] | None,
) -> DeepSearchDecision:
    """
    Decide whether normal FIX_BUG analysis should escalate to Deep Search.

    Call after normal code analysis and before terminal triage.
    The service must call this only for FIX_BUG requests that were not
    already selected for Deep Search.
    """
    normalized_query = str(query or "").strip()
    chunk_count = len(retrieved_chunks) if retrieved_chunks else 0

    logger.debug(
        "deep_search_escalation_check_started",
        extra={
            "retrieved_chunk_count": chunk_count,
            "analysis_result_available": isinstance(analysis_result, dict),
            "query_length": len(normalized_query),
        },
    )

    if not retrieved_chunks:
        return _decision(
            selected=True,
            reason=(
                "Normal retrieval returned no usable code chunks. "
                "Escalating to locate relevant evidence."
            ),
            event="deep_search_escalation_selected",
            category="no_retrieved_chunks",
            retrieved_chunk_count=0,
        )

    if not isinstance(analysis_result, dict):
        return _decision(
            selected=True,
            reason=(
                "Normal analysis did not produce a usable result. "
                "Escalating to investigate the bug."
            ),
            event="deep_search_escalation_selected",
            category="invalid_analysis_result",
            retrieved_chunk_count=chunk_count,
        )

    analysis_status = str(
        analysis_result.get("analysis_status", "")
    ).strip().upper()

    logger.debug(
        "deep_search_escalation_analysis_status",
        extra={
            "analysis_status": analysis_status or "NOT_PROVIDED",
            "retrieved_chunk_count": chunk_count,
        },
    )

    if analysis_status in {
        "UNAVAILABLE",
        "INSUFFICIENT_EVIDENCE",
        "AMBIGUOUS",
        "INCOMPLETE",
        "FAILED",
    }:
        return _decision(
            selected=True,
            reason=(
                f"Normal analysis status is {analysis_status}. "
                "Escalating for bounded evidence gathering."
            ),
            event="deep_search_escalation_selected",
            category="analysis_status",
            analysis_status=analysis_status,
            retrieved_chunk_count=chunk_count,
        )

    evidence_summary = str(
        analysis_result.get("evidence_summary", "")
    ).lower()

    cross_component_signals = (
        ("has_no_attribute", "has no attribute"),
        ("field_missing", "field missing"),
        ("field_not_found", "field not found"),
        ("attribute_error", "attribute error"),
        ("wrong_field", "wrong field"),
        ("missing_field", "missing field"),
        ("mapping_mismatch", "mapping mismatch"),
        ("contract_mismatch", "contract mismatch"),
        ("insufficient_evidence", "insufficient evidence"),
        ("ambiguous", "ambiguous"),
    )

    for category, signal in cross_component_signals:
        if signal in evidence_summary:
            return _decision(
                selected=True,
                reason=(
                    "Normal analysis indicates a possible contract mismatch, "
                    "ambiguity, or evidence gap. Deep Search should verify "
                    "the dependency chain before proposing a fix."
                ),
                event="deep_search_escalation_selected",
                category=category,
                retrieved_chunk_count=chunk_count,
            )

    query_signal_groups = (
        ("attribute_error", _ATTRIBUTE_ERROR_PATTERNS),
        ("cross_component", _CROSS_COMPONENT_PATTERNS),
        ("cross_file", _CROSS_FILE_PATTERNS),
        ("page_error", _PAGE_ERROR_PATTERNS),
    )

    for category, patterns in query_signal_groups:
        matched_pattern = _find_matching_pattern(
            normalized_query,
            patterns,
        )

        if matched_pattern is not None:
            return _decision(
                selected=True,
                reason=(
                    "The query indicates a potential cross-component issue "
                    "that normal analysis has not conclusively resolved."
                ),
                event="deep_search_escalation_selected",
                category=f"query_{category}",
                retrieved_chunk_count=chunk_count,
            )

    return _decision(
        selected=False,
        reason=(
            "No recognized escalation signal; preserve the normal FIX_BUG flow."
        ),
        event="deep_search_escalation_skipped",
        category="no_escalation_signal",
        analysis_status=analysis_status or "NOT_PROVIDED",
        retrieved_chunk_count=chunk_count,
    )


def _find_matching_pattern(
    query: str,
    patterns: tuple[str, ...],
) -> str | None:
    """Return the first matching pattern, or None."""
    for pattern in patterns:
        if re.search(pattern, query, flags=re.IGNORECASE | re.DOTALL):
            return pattern

    return None


def _matches(query: str, patterns: tuple[str, ...]) -> bool:
    """Return True when any routing pattern matches the query."""
    return _find_matching_pattern(query, patterns) is not None


def _decision(
    *,
    selected: bool,
    reason: str,
    event: str,
    category: str,
    **metadata: Any,
) -> DeepSearchDecision:
    """Log a routing decision consistently and return its result."""
    log_metadata = {
        "selected": selected,
        "category": category,
        "reason": reason,
        **metadata,
    }

    if selected:
        logger.info(event, extra=log_metadata)
    else:
        logger.debug(event, extra=log_metadata)

    return DeepSearchDecision(selected=selected, reason=reason)
