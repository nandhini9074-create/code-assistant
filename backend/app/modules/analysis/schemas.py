"""
app/modules/analysis/schemas.py
JSON Schemas for structured LLM analysis outputs.
"""

from __future__ import annotations

from typing import Any

# Schema for the intelligent intent-based chunk analysis
INTENT_ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "A concise summary of how these code chunks address the user's intent.",
        },
        "key_findings": {
            "type": "array",
            "items": {
                "type": "string"
            },
            "description": "A list of bullet points detailing the most important insights from the code.",
        },
        "files_referenced": {
            "type": "array",
            "items": {
                "type": "string"
            },
            "description": "A list of file paths that were analyzed to form this conclusion.",
        },
        "confidence_score": {
            "type": "number",
            "description": "A score from 0.0 to 1.0 indicating how confident you are that the context fully addresses the intent.",
        },
    },
    "required": ["summary", "key_findings", "files_referenced", "confidence_score"],
    "additionalProperties": False,
}
