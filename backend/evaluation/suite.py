"""
evaluation/suite.py
EvaluationSuite: single-command orchestrator for the complete Phase 3 evaluation pipeline.

Ties together:
    - Dataset loading and validation (Phase 1)
    - EvaluationRunner (Phase 2)
    - ThresholdChecker (Phase 3)
    - MarkdownReportRenderer + VersionedJsonWriter (Phase 3)

Usage:
    suite = EvaluationSuite(
        dataset_path="evaluation/datasets/sample_evaluation_dataset.json",
        intent_adapter=ProductionIntentAdapter(deterministic_only=True),
        thresholds=ThresholdConfig(min_intent_accuracy=0.7),
        output_dir=Path("evaluation/results"),
    )
    outcome = await suite.run()
    print(outcome.markdown_report)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.logging import get_logger
from evaluation.adapters.base import BaseIntentAdapter, BaseRetrieverAdapter
from evaluation.config import EvaluationConfig, get_evaluation_config
from evaluation.dataset import DatasetLoader
from evaluation.exceptions import DatasetLoadError, DatasetValidationError
from evaluation.reporting import (
    OUTCOME_BLOCKED,
    OUTCOME_FAILURES,
    OUTCOME_SUCCESS,
    MarkdownReportRenderer,
    VersionedJsonWriter,
)
from evaluation.results import EvaluationReport
from evaluation.runner import EvaluationRunner
from evaluation.thresholds import ThresholdChecker, ThresholdConfig, ThresholdResult

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Suite outcome data class
# ---------------------------------------------------------------------------


@dataclass
class SuiteOutcome:
    """
    Result of a complete EvaluationSuite run.

    outcome_code is one of:
        SUCCESS              – all thresholds passed, no adapter errors
        COMPLETED_WITH_FAILURES – some adapter errors, but thresholds not configured or passed
        BELOW_THRESHOLD      – at least one configured threshold was not met
        BLOCKED              – suite could not run (bad dataset, no adapters, etc.)
    """

    outcome_code: str
    report: Optional[EvaluationReport]
    threshold_result: Optional[ThresholdResult]
    markdown_report: str
    json_report_path: Optional[Path]
    blocking_errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.outcome_code == OUTCOME_SUCCESS


# ---------------------------------------------------------------------------
# Suite orchestrator
# ---------------------------------------------------------------------------


class EvaluationSuite:
    """
    Orchestrates the complete evaluation pipeline in one call.

    Does NOT modify production code, API routes, ingestion, or database schemas.

    Args:
        dataset_path:        Path to the evaluation dataset (.json or .jsonl).
        intent_adapter:      Optional intent adapter for intent evaluation.
        retriever_adapter:   Optional retriever adapter for retrieval evaluation.
        thresholds:          Optional ThresholdConfig.  When None, thresholds are not checked.
        output_dir:          Directory to write versioned JSON result files.
                             When None, no file is written.
        k:                   Rank cut-off for retrieval metrics (default 5).
        default_collection:  Fallback Qdrant collection for items without collection_name.
        config:              EvaluationConfig override.
        extra_metadata:      Arbitrary key-value pairs embedded in the JSON result.
    """

    def __init__(
        self,
        dataset_path: str | Path,
        intent_adapter: Optional[BaseIntentAdapter] = None,
        retriever_adapter: Optional[BaseRetrieverAdapter] = None,
        thresholds: Optional[ThresholdConfig] = None,
        output_dir: Optional[Path] = None,
        k: int = 5,
        default_collection: Optional[str] = None,
        config: Optional[EvaluationConfig] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.dataset_path = Path(dataset_path)
        self.intent_adapter = intent_adapter
        self.retriever_adapter = retriever_adapter
        self.thresholds = thresholds
        self.output_dir = Path(output_dir) if output_dir else None
        self.k = k
        self.default_collection = default_collection
        self.config = config or get_evaluation_config()
        self.extra_metadata = extra_metadata or {}

        self._renderer = MarkdownReportRenderer()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> SuiteOutcome:
        """
        Execute the complete evaluation suite and return a SuiteOutcome.

        Outcome codes:
            SUCCESS              – evaluation completed, all thresholds passed (or not configured)
            COMPLETED_WITH_FAILURES – adapter errors occurred but no threshold check failed
            BELOW_THRESHOLD      – one or more configured thresholds were not met
            BLOCKED              – suite could not run at all (missing dataset, no adapters, etc.)
        """
        blocking_errors: List[str] = []
        warnings: List[str] = []

        # ---- Step 1: Load and validate dataset ----
        dataset = self._load_dataset(blocking_errors)
        if dataset is None:
            return self._blocked_outcome(blocking_errors)

        # ---- Step 2: Check that at least one adapter is available ----
        if self.intent_adapter is None and self.retriever_adapter is None:
            blocking_errors.append(
                "EvaluationSuite requires at least one adapter (intent_adapter or retriever_adapter). "
                "No evaluation can run without an adapter."
            )
            return self._blocked_outcome(blocking_errors)

        # ---- Step 3: Run evaluation (Phase 2) ----
        try:
            runner = EvaluationRunner(
                retriever_adapter=self.retriever_adapter,
                intent_adapter=self.intent_adapter,
                config=self.config,
            )
            report = await runner.run(
                dataset,
                k=self.k,
                default_collection=self.default_collection,
            )
        except Exception as exc:
            blocking_errors.append(f"EvaluationRunner raised an unexpected error: {exc}")
            return self._blocked_outcome(blocking_errors)

        # ---- Step 4: Threshold check (Phase 3) ----
        threshold_result: Optional[ThresholdResult] = None
        if self.thresholds is not None:
            checker = ThresholdChecker(self.thresholds)
            threshold_result = checker.check(report)
            warnings.extend(threshold_result.warnings)

        # ---- Step 5: Determine outcome code ----
        outcome_code = self._resolve_outcome(report, threshold_result)

        # ---- Step 6: Render Markdown ----
        config_summary = {
            "dataset_path": str(self.dataset_path),
            "k": self.k,
            "thresholds_configured": self.thresholds is not None,
        }
        markdown = self._renderer.render(
            report=report,
            threshold_result=threshold_result,
            config_summary=config_summary,
            outcome=outcome_code,
        )

        # ---- Step 7: Write versioned JSON ----
        json_path: Optional[Path] = None
        if self.output_dir is not None:
            try:
                writer = VersionedJsonWriter(self.output_dir)
                json_path = writer.write(
                    report=report,
                    threshold_result=threshold_result,
                    outcome=outcome_code,
                    extra_metadata={
                        "dataset_path": str(self.dataset_path),
                        "k": self.k,
                        **self.extra_metadata,
                    },
                )
                logger.info("suite_json_report_written", path=str(json_path))
            except Exception as exc:
                warnings.append(f"Failed to write versioned JSON report: {exc}")

        logger.info(
            "evaluation_suite_completed",
            outcome=outcome_code,
            dataset=dataset.dataset_name,
        )

        return SuiteOutcome(
            outcome_code=outcome_code,
            report=report,
            threshold_result=threshold_result,
            markdown_report=markdown,
            json_report_path=json_path,
            blocking_errors=blocking_errors,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_dataset(self, blocking_errors: List[str]):
        """Load and validate dataset; append error messages and return None on failure."""
        loader = DatasetLoader(config=self.config)
        try:
            return loader.load_from_file(
                self.dataset_path, validate=True, strict=True
            )
        except DatasetLoadError as exc:
            blocking_errors.append(f"Dataset load failed: {exc}")
        except DatasetValidationError as exc:
            blocking_errors.append(f"Dataset validation failed: {exc}")
        except Exception as exc:
            blocking_errors.append(f"Unexpected error loading dataset: {exc}")
        return None

    def _blocked_outcome(self, blocking_errors: List[str]) -> SuiteOutcome:
        """Build a BLOCKED SuiteOutcome when the suite cannot run."""
        error_list = "\n".join(f"- {e}" for e in blocking_errors)
        markdown = (
            "# RepoLens Evaluation Report 🚫\n\n"
            f"> **Outcome:** `{OUTCOME_BLOCKED}`\n\n"
            "## Blocking Errors\n\n"
            f"{error_list}\n\n"
            "Resolve the errors above and re-run the evaluation suite.\n"
        )
        return SuiteOutcome(
            outcome_code=OUTCOME_BLOCKED,
            report=None,
            threshold_result=None,
            markdown_report=markdown,
            json_report_path=None,
            blocking_errors=blocking_errors,
        )

    @staticmethod
    def _resolve_outcome(
        report: EvaluationReport,
        threshold_result: Optional[ThresholdResult],
    ) -> str:
        """Determine the outcome code from the report and threshold check."""
        from evaluation.reporting import OUTCOME_BELOW_THRESHOLD

        if report.retrieval is None and report.intent is None:
            return OUTCOME_BLOCKED

        if threshold_result is not None and not threshold_result.passed:
            return OUTCOME_BELOW_THRESHOLD

        has_failures = (
            (report.retrieval is not None and report.retrieval.failed_queries > 0)
            or (report.intent is not None and report.intent.failed_queries > 0)
        )
        if has_failures:
            return OUTCOME_FAILURES

        return OUTCOME_SUCCESS
