"""
evaluation/reporting.py
Markdown report renderer and versioned JSON writer for Phase 3.

Consumes EvaluationReport (Phase 2) and ThresholdResult (Phase 3)
and produces:
    - A human-readable Markdown report string
    - A versioned JSON result file on disk (filename includes timestamp)

No production code is imported or modified here.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from evaluation.results import (
    EvaluationReport,
    IntentEvaluationReport,
    RetrievalEvaluationReport,
)
from evaluation.thresholds import ThresholdResult

# Schema version for JSON result files – bump when the schema changes.
REPORT_SCHEMA_VERSION = "3.0"


# ---------------------------------------------------------------------------
# Outcome constants
# ---------------------------------------------------------------------------

OUTCOME_SUCCESS = "SUCCESS"
OUTCOME_FAILURES = "COMPLETED_WITH_FAILURES"
OUTCOME_BELOW_THRESHOLD = "BELOW_THRESHOLD"
OUTCOME_BLOCKED = "BLOCKED"


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------


class MarkdownReportRenderer:
    """
    Renders an EvaluationReport + ThresholdResult as a Markdown document.

    The rendered document includes:
        - Run metadata (dataset, timestamp, configuration)
        - Retrieval metrics section
        - Intent classification section (accuracy, per-class table, macro-F1, confusion matrix)
        - Threshold check summary
        - Dataset health summary (size, evaluated, failed, skipped, exclusion reasons)
        - How-to notes for adding queries and verifying ground-truth labels
    """

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def render(
        self,
        report: EvaluationReport,
        threshold_result: Optional[ThresholdResult] = None,
        config_summary: Optional[Dict[str, Any]] = None,
        outcome: Optional[str] = None,
    ) -> str:
        """
        Render the full Markdown report.

        Args:
            report:           Combined EvaluationReport from EvaluationRunner.
            threshold_result: Optional ThresholdResult from ThresholdChecker.
            config_summary:   Optional dict of configuration values to include.
            outcome:          One of OUTCOME_* constants.  Computed automatically
                              from threshold_result when not supplied.

        Returns:
            Multi-line Markdown string.
        """
        lines: List[str] = []

        resolved_outcome = outcome or self._resolve_outcome(report, threshold_result)

        lines += self._section_header(report, resolved_outcome)
        lines += self._section_run_metadata(report, config_summary)
        lines += self._section_dataset_health(report)

        if report.retrieval is not None:
            lines += self._section_retrieval(report.retrieval)

        if report.intent is not None:
            lines += self._section_intent(report.intent)

        if threshold_result is not None:
            lines += self._section_thresholds(threshold_result)

        lines += self._section_guidance()

        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    def _section_header(self, report: EvaluationReport, outcome: str) -> List[str]:
        icon = {
            OUTCOME_SUCCESS: "✅",
            OUTCOME_FAILURES: "⚠️",
            OUTCOME_BELOW_THRESHOLD: "🔴",
            OUTCOME_BLOCKED: "🚫",
        }.get(outcome, "ℹ️")

        return [
            f"# RepoLens Evaluation Report {icon}",
            "",
            f"> **Outcome:** `{outcome}`",
            f"> **Dataset:** {report.dataset_name}",
            f"> **Generated:** {report.evaluated_at}",
            "",
        ]

    # ------------------------------------------------------------------
    # Run metadata
    # ------------------------------------------------------------------

    def _section_run_metadata(
        self,
        report: EvaluationReport,
        config_summary: Optional[Dict[str, Any]],
    ) -> List[str]:
        lines = ["## Run Configuration", ""]
        k = report.retrieval.k if report.retrieval else "N/A"
        lines += [
            f"| Parameter          | Value |",
            f"|:-------------------|:------|",
            f"| Rank cut-off K     | {k}   |",
            f"| Schema version     | {REPORT_SCHEMA_VERSION} |",
        ]
        if config_summary:
            for key, val in config_summary.items():
                lines.append(f"| {key:<18} | {val} |")
        lines.append("")
        return lines

    # ------------------------------------------------------------------
    # Dataset health
    # ------------------------------------------------------------------

    def _section_dataset_health(self, report: EvaluationReport) -> List[str]:
        lines = ["## Dataset Health", ""]

        sections = []
        if report.retrieval is not None:
            sections.append(("Retrieval", report.retrieval))
        if report.intent is not None:
            sections.append(("Intent", report.intent))

        for label, sub in sections:
            total = sub.total_queries
            evaluated = sub.evaluated_queries
            skipped = sub.skipped_queries
            failed = sub.failed_queries

            lines += [
                f"### {label}",
                "",
                f"| Metric              | Count |",
                f"|:--------------------|------:|",
                f"| Total queries       | {total} |",
                f"| Evaluated           | {evaluated} |",
                f"| Skipped             | {skipped} |",
                f"| Failed (adapter error) | {failed} |",
                "",
            ]

            # Exclusion reasons
            if skipped > 0 or failed > 0:
                lines.append("**Exclusion reasons:**")
                lines.append("")
                if label == "Retrieval" and skipped > 0:
                    # Collect unique skip reasons from per_query
                    no_coll = sum(
                        1 for q in sub.per_query
                        if q.skipped and q.collection_name == ""
                    )
                    no_chunks = skipped - no_coll
                    if no_coll:
                        lines.append(
                            f"- **{no_coll}** item(s) skipped: no `collection_name` and no default collection provided."
                        )
                    if no_chunks > 0:
                        lines.append(
                            f"- **{no_chunks}** item(s) skipped: no `expected_chunks` (ground-truth labels missing)."
                        )
                if failed > 0:
                    lines.append(
                        f"- **{failed}** item(s) failed: adapter raised an error during evaluation. "
                        f"See per-query detail in the versioned JSON report."
                    )
                lines.append("")

        return lines

    # ------------------------------------------------------------------
    # Retrieval metrics section
    # ------------------------------------------------------------------

    def _section_retrieval(self, ret: RetrievalEvaluationReport) -> List[str]:
        k = ret.k
        lines = [f"## Retrieval Metrics (k={k})", ""]

        lines += [
            "| Metric             | Score  |",
            "|:-------------------|-------:|",
            f"| Precision@{k:<7}  | {ret.mean_precision_at_k:.4f} |",
            f"| Recall@{k:<9}  | {ret.mean_recall_at_k:.4f} |",
            f"| MRR               | {ret.mrr:.4f} |",
        ]
        if ret.mean_ndcg_at_k is not None:
            lines.append(f"| nDCG@{k:<11}  | {ret.mean_ndcg_at_k:.4f} |")
        else:
            lines.append(f"| nDCG@{k:<11}  | N/A *(no graded labels)* |")

        lines.append("")

        # Per-query breakdown (failed / skipped only)
        problem_queries = [q for q in ret.per_query if q.skipped or q.error]
        if problem_queries:
            lines.append("### Per-query Issues")
            lines.append("")
            lines.append("| Query ID | Issue |")
            lines.append("|:---------|:------|")
            for q in problem_queries:
                reason = "skipped" if q.skipped else f"error: {q.error}"
                lines.append(f"| `{q.query_id}` | {reason} |")
            lines.append("")

        return lines

    # ------------------------------------------------------------------
    # Intent classification section
    # ------------------------------------------------------------------

    def _section_intent(self, intent: IntentEvaluationReport) -> List[str]:
        lines = ["## Intent Classification Metrics", ""]

        macro_f1 = self._compute_macro_f1(intent.per_class_metrics)

        lines += [
            "| Metric        | Score  |",
            "|:--------------|-------:|",
            f"| Accuracy      | {intent.accuracy:.4f} |",
            f"| Macro F1      | {macro_f1:.4f} |",
            "",
        ]

        # Per-class table
        if intent.per_class_metrics:
            lines += [
                "### Per-class Breakdown",
                "",
                "| Intent              | Precision | Recall | F1     | Support |",
                "|:--------------------|----------:|-------:|-------:|--------:|",
            ]
            for cls in sorted(intent.per_class_metrics):
                m = intent.per_class_metrics[cls]
                lines.append(
                    f"| {cls:<19} | {m['precision']:>9.4f} | {m['recall']:>6.4f} | {m['f1']:>6.4f} | {int(m['support']):>7} |"
                )
            lines.append("")

        # Confusion matrix
        if intent.confusion_matrix:
            lines += self._render_confusion_matrix(intent.confusion_matrix)

        return lines

    def _render_confusion_matrix(
        self, matrix: Dict[str, Dict[str, int]]
    ) -> List[str]:
        """Render the confusion matrix as a Markdown table."""
        labels = sorted(matrix.keys())
        # Exclude __none__ from column headers unless it has non-zero entries
        pred_labels = sorted(
            {
                pred
                for row in matrix.values()
                for pred, cnt in row.items()
                if cnt > 0 or pred != "__none__"
            }
        )

        header = "| True \\ Predicted | " + " | ".join(f"{lbl[:10]}" for lbl in pred_labels) + " |"
        sep = "|:---" + ("|---:" * len(pred_labels)) + "|"

        lines = ["### Confusion Matrix", "", header, sep]
        for true_lbl in labels:
            row_cells = [str(matrix[true_lbl].get(p, 0)) for p in pred_labels]
            lines.append(f"| {true_lbl[:17]:<17} | " + " | ".join(row_cells) + " |")
        lines.append("")
        return lines

    # ------------------------------------------------------------------
    # Threshold section
    # ------------------------------------------------------------------

    def _section_thresholds(self, result: ThresholdResult) -> List[str]:
        status = "✅ All thresholds passed" if result.passed else f"🔴 {len(result.failures)} threshold(s) failed"
        lines = ["## Threshold Check", "", f"**Status:** {status}", ""]

        if result.failures:
            lines += [
                "### Failures",
                "",
                "| Metric | Actual | Threshold | Detail |",
                "|:-------|-------:|----------:|:-------|",
            ]
            for f in result.failures:
                lines.append(
                    f"| `{f.metric}` | {f.actual:.4f} | {f.threshold:.4f} | {f.message} |"
                )
            lines.append("")

        if result.warnings:
            lines.append("### Warnings")
            lines.append("")
            for w in result.warnings:
                lines.append(f"- {w}")
            lines.append("")

        if result.checked_metrics:
            lines += [
                "### Checked Metrics",
                "",
                "| Metric | Value |",
                "|:-------|------:|",
            ]
            for metric, val in sorted(result.checked_metrics.items()):
                lines.append(f"| `{metric}` | {val:.4f} |")
            lines.append("")

        if result.skipped_metrics:
            skipped_str = ", ".join(f"`{m}`" for m in result.skipped_metrics)
            lines.append(f"**Skipped (no threshold configured):** {skipped_str}")
            lines.append("")

        return lines

    # ------------------------------------------------------------------
    # Guidance section
    # ------------------------------------------------------------------

    @staticmethod
    def _section_guidance() -> List[str]:
        return [
            "## How to Add New Evaluation Queries",
            "",
            "1. Open `evaluation/datasets/sample_evaluation_dataset.json` (or your custom dataset file).",
            "2. Add a new entry to the `items` array:",
            "   ```json",
            '   {',
            '     "query_id": "eval-q07",',
            '     "query": "Your natural language query here",',
            '     "expected_intent": "RETRIEVE",',
            '     "repository": "your-repo-name",',
            '     "collection_name": "qdrant_collection_name",',
            '     "expected_chunks": [',
            '       {"chunk_id": "chunk_hash_value", "relevance_grade": 3.0,',
            '        "file_path": "path/to/file.py", "symbol_name": "FunctionName"}',
            '     ]',
            '   }',
            "   ```",
            "3. **Ground-truth chunk IDs**: retrieve the `chunk_hash` from Qdrant by running a search",
            "   and inspecting the payload of the most relevant point.",
            "4. **Relevance grades**: use the 0–4 scale:",
            "   - 4 = perfectly relevant (the exact answer)",
            "   - 3 = highly relevant",
            "   - 2 = partially relevant",
            "   - 1 = marginally relevant",
            "   - 0 = not relevant (omit from expected_chunks)",
            "5. **Verify ground-truth**: manually confirm that each listed chunk actually",
            "   addresses the query.  Use `python -m evaluation.cli inspect <dataset>` to review.",
            "6. **Run validation**: `python -m evaluation.cli validate <dataset>` before committing.",
            "7. **Incompatible datasets**: when comparing results across runs, ensure both used",
            "   the same dataset version.  Warn explicitly when `dataset_name` or `version` differ.",
            "",
            "## Known Limitations",
            "",
            "- Retrieval evaluation requires a **live Qdrant connection**.  Offline CLI mode",
            "  runs intent-only evaluation using the deterministic fallback classifier.",
            "- Chunk IDs in `expected_chunks` must match the **exact `chunk_hash`** stored in",
            "  Qdrant.  Stale IDs after re-indexing will cause false negatives.",
            "- nDCG is only computed when at least one chunk has a relevance grade != 1.0",
            "  (binary-relevance datasets report nDCG as N/A).",
            "- Thresholds are project configuration and should be reviewed alongside dataset",
            "  size and coverage before interpreting pass/fail as a quality signal.",
            "",
        ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_outcome(
        report: EvaluationReport,
        threshold_result: Optional[ThresholdResult],
    ) -> str:
        if report.retrieval is None and report.intent is None:
            return OUTCOME_BLOCKED
        has_failures = (
            (report.retrieval is not None and report.retrieval.failed_queries > 0)
            or (report.intent is not None and report.intent.failed_queries > 0)
        )
        if threshold_result is not None and not threshold_result.passed:
            return OUTCOME_BELOW_THRESHOLD
        if has_failures:
            return OUTCOME_FAILURES
        return OUTCOME_SUCCESS

    @staticmethod
    def _compute_macro_f1(per_class: Dict[str, Dict[str, float]]) -> float:
        if not per_class:
            return 0.0
        f1_values = [m.get("f1", 0.0) for m in per_class.values()]
        return sum(f1_values) / len(f1_values) if f1_values else 0.0


# ---------------------------------------------------------------------------
# Versioned JSON writer
# ---------------------------------------------------------------------------


class VersionedJsonWriter:
    """
    Writes an EvaluationReport and optional ThresholdResult to a versioned
    JSON file on disk.

    The filename includes the dataset name, schema version, and UTC timestamp
    so successive runs do not overwrite each other:
        <output_dir>/<dataset_slug>_v3.0_20261021T120000Z.json
    """

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = Path(output_dir)

    def write(
        self,
        report: EvaluationReport,
        threshold_result: Optional[ThresholdResult] = None,
        outcome: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> Path:
        """
        Serialise and write the full evaluation artefact to disk.

        Returns:
            Absolute path to the written file.
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        slug = re.sub(r"[^a-zA-Z0-9_-]", "_", report.dataset_name)[:40]
        filename = f"{slug}_v{REPORT_SCHEMA_VERSION}_{timestamp}.json"
        out_path = self.output_dir / filename

        payload: Dict[str, Any] = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "outcome": outcome or MarkdownReportRenderer._resolve_outcome(report, threshold_result),
            "generated_at": timestamp,
            "evaluation": report.model_dump(mode="json"),
        }
        if threshold_result is not None:
            payload["threshold_check"] = threshold_result.model_dump(mode="json")
        if extra_metadata:
            payload["metadata"] = extra_metadata

        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return out_path
