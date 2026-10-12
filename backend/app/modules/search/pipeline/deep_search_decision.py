
"""
app/modules/search/pipeline/deep_search_decision.py

Deterministic routing decision for the optional FIX_BUG Deep Search
workflow.

This module:
- Uses the existing classified intent.
- Evaluates the original user query before ordinary Qdrant retrieval.
- Selects Deep Search for explicit cross-file or dependency tracing.
- Leaves other intents and ordinary FIX_BUG requests unchanged.
- Does not perform retrieval, dependency exploration, or LLM calls.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class DeepSearchDecision:
    """Result of the Deep Search routing decision."""

    selected: bool
    reason: str


# Explicit requests to trace behavior across components or files.
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
    r"\bfind\s+(?:where|which\s+file)\s+.+\b(?:called|defined|used|passed)\b",
    r"\bfrontend\b.*\bbackend\b|\bbackend\b.*\bfrontend\b",
    r"\broute\b.*\bservice\b.*\bmodel\b",
    r"\btemplate\b.*\bmodel\b|\bmodel\b.*\btemplate\b",
)

# Signals that a bug may require following runtime data or dependencies.
_CROSS_COMPONENT_PATTERNS = (
    r"\bwrong\s+(?:field|attribute|property)\b",
    r"\bmissing\s+(?:field|attribute|property)\b",
    r"\bundefined\s+(?:field|attribute|property|variable)\b",
    r"\bdoes\s+not\s+exist\s+on\b",
    r"\bnot\s+defined\s+in\b",
    r"\bpassed\s+from\b",
    r"\breturned\s+by\b",
    r"\bconsumed\s+by\b",
    r"\bdata\s+flow\b",
    r"\bcall\s+chain\b",
    r"\bcaller\b.*\bcallee\b|\bcallee\b.*\bcaller\b",
    r"\bmultiple\s+possible\s+locations\b",
    r"\bambiguous\s+(?:function|method|symbol|file|implementation)\b",
)

# Explicit preference for a deeper investigation.
_EXPLICIT_DEEP_SEARCH_PATTERNS = (
    r"\bdeep\s+search\b",
    r"\bdeeply\s+investigate\b",
    r"\binvestigate\s+across\s+files\b",
    r"\btrace\s+the\s+full\s+flow\b",
    r"\bperform\s+(?:a\s+)?root[- ]cause\s+analysis\b",
)


def decide_deep_search(
    *,
    intent: str,
    query: str,
) -> DeepSearchDecision:
    """
    Decide whether a request should use Deep Search.

    Call after existing intent classification and before the first
    ordinary Qdrant retrieval.

    Only FIX_BUG requests can be selected. The default is the
    existing normal pipeline.
    """
    normalized_intent = str(intent or "").strip().upper()
    normalized_query = str(query or "").strip().lower()

    if normalized_intent != "FIX_BUG":
        return DeepSearchDecision(
            selected=False,
            reason="Intent is not FIX_BUG; preserve the existing flow.",
        )

    if not normalized_query:
        return DeepSearchDecision(
            selected=False,
            reason="Query is empty; use the existing pipeline behavior.",
        )

    if _matches(
        normalized_query,
        _EXPLICIT_DEEP_SEARCH_PATTERNS,
    ):
        return DeepSearchDecision(
            selected=True,
            reason="The user explicitly requested deeper investigation.",
        )

    if _matches(
        normalized_query,
        _CROSS_FILE_PATTERNS,
    ):
        return DeepSearchDecision(
            selected=True,
            reason="The query requests cross-file or dependency tracing.",
        )

    if _matches(
        normalized_query,
        _CROSS_COMPONENT_PATTERNS,
    ):
        return DeepSearchDecision(
            selected=True,
            reason="The query suggests a cross-component bug investigation.",
        )

    return DeepSearchDecision(
        selected=False,
        reason="No explicit deep-investigation signal; use the normal flow.",
    )


def _matches(query: str, patterns: tuple[str, ...]) -> bool:
    """Return True when any routing signal matches the query."""
    return any(re.search(pattern, query) for pattern in patterns)
