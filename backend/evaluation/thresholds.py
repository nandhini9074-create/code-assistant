"""
evaluation/thresholds.py
Configurable acceptance thresholds for evaluation metrics.

Thresholds are *project configuration*, not performance guarantees.
A threshold check tells you whether the metric meets the minimum bar
you have decided to set for this project.  It does NOT imply the model
is objectively good or bad.

Usage:
    from evaluation.thresholds import ThresholdConfig, ThresholdChecker, ThresholdResult

    cfg = ThresholdConfig(
        min_recall_at_k=0.6,
        min_mrr=0.5,
        min_intent_accuracy=0.75,
    )
    checker = ThresholdChecker(cfg)
    result  = checker.check(evaluation_report)
    if not result.passed:
        for failure in result.failures:
            print(failure.message)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from evaluation.results import EvaluationReport


# ---------------------------------------------------------------------------
# Threshold configuration
# ---------------------------------------------------------------------------


class ThresholdConfig(BaseModel):
    """
    Minimum acceptance thresholds for evaluation metrics.

    All thresholds are optional.  When a threshold is None the corresponding
    metric is not checked.  All values are in [0.0, 1.0] unless noted.
    """

    # --- Retrieval thresholds ---
    min_recall_at_k: Optional[float] = Field(
        default=None,
        description="Minimum required mean Recall@K (e.g. 0.6).",
    )
    min_precision_at_k: Optional[float] = Field(
        default=None,
        description="Minimum required mean Precision@K.",
    )
    min_mrr: Optional[float] = Field(
        default=None,
        description="Minimum required Mean Reciprocal Rank.",
    )
    min_ndcg_at_k: Optional[float] = Field(
        default=None,
        description="Minimum required mean nDCG@K (only checked when nDCG was computed).",
    )

    # --- Intent classification thresholds ---
    min_intent_accuracy: Optional[float] = Field(
        default=None,
        description="Minimum required overall intent accuracy (e.g. 0.75).",
    )
    min_intent_macro_f1: Optional[float] = Field(
        default=None,
        description="Minimum required macro-averaged F1 across all intent classes.",
    )

    # --- Dataset health thresholds ---
    max_failed_query_fraction: Optional[float] = Field(
        default=None,
        description=(
            "Maximum allowed fraction of queries that failed (error during adapter call). "
            "E.g. 0.1 means at most 10%% of queries may fail."
        ),
    )

    class Config:
        extra = "forbid"


# ---------------------------------------------------------------------------
# Threshold check result types
# ---------------------------------------------------------------------------


class ThresholdFailure(BaseModel):
    """Represents a single metric that did not meet its configured threshold."""

    metric: str = Field(..., description="Name of the metric that failed.")
    actual: float = Field(..., description="Observed metric value.")
    threshold: float = Field(..., description="Configured minimum threshold.")
    message: str = Field(..., description="Human-readable failure description.")


class ThresholdResult(BaseModel):
    """Outcome of a threshold check against an EvaluationReport."""

    passed: bool = Field(..., description="True if all configured thresholds were met.")
    failures: List[ThresholdFailure] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    checked_metrics: Dict[str, Any] = Field(
        default_factory=dict,
        description="Dict of all metrics that were checked and their observed values.",
    )
    skipped_metrics: List[str] = Field(
        default_factory=list,
        description="Metric names that were skipped because no threshold was configured.",
    )


# ---------------------------------------------------------------------------
# Threshold checker
# ---------------------------------------------------------------------------


class ThresholdChecker:
    """
    Applies a ThresholdConfig to an EvaluationReport and returns a ThresholdResult.

    Does not modify or depend on the production search pipeline.
    """

    def __init__(self, config: ThresholdConfig) -> None:
        self.config = config

    def check(self, report: EvaluationReport) -> ThresholdResult:
        """
        Check all configured thresholds against the EvaluationReport.

        Args:
            report: The EvaluationReport produced by EvaluationRunner.run().

        Returns:
            ThresholdResult with pass/fail status and per-metric details.
        """
        failures: List[ThresholdFailure] = []
        warnings: List[str] = []
        checked: Dict[str, Any] = {}
        skipped: List[str] = []

        # ---- Retrieval checks ----
        if report.retrieval is not None:
            ret = report.retrieval

            self._check_metric(
                name="mean_recall_at_k",
                actual=ret.mean_recall_at_k,
                threshold=self.config.min_recall_at_k,
                checked=checked,
                skipped=skipped,
                failures=failures,
            )
            self._check_metric(
                name="mean_precision_at_k",
                actual=ret.mean_precision_at_k,
                threshold=self.config.min_precision_at_k,
                checked=checked,
                skipped=skipped,
                failures=failures,
            )
            self._check_metric(
                name="mrr",
                actual=ret.mrr,
                threshold=self.config.min_mrr,
                checked=checked,
                skipped=skipped,
                failures=failures,
            )

            # nDCG: only check when results include nDCG (graded labels present)
            if ret.mean_ndcg_at_k is not None:
                self._check_metric(
                    name="mean_ndcg_at_k",
                    actual=ret.mean_ndcg_at_k,
                    threshold=self.config.min_ndcg_at_k,
                    checked=checked,
                    skipped=skipped,
                    failures=failures,
                )
            elif self.config.min_ndcg_at_k is not None:
                warnings.append(
                    "min_ndcg_at_k threshold is configured but nDCG was not computed "
                    "(no graded relevance labels in dataset). Threshold skipped."
                )
                skipped.append("mean_ndcg_at_k")

            # Failed-query fraction check
            total = ret.total_queries
            if total > 0 and self.config.max_failed_query_fraction is not None:
                frac = ret.failed_queries / total
                checked["failed_query_fraction"] = frac
                if frac > self.config.max_failed_query_fraction:
                    failures.append(
                        ThresholdFailure(
                            metric="failed_query_fraction",
                            actual=frac,
                            threshold=self.config.max_failed_query_fraction,
                            message=(
                                f"Failed query fraction {frac:.2%} exceeds maximum "
                                f"{self.config.max_failed_query_fraction:.2%}."
                            ),
                        )
                    )
        else:
            # Report has no retrieval section – skip all retrieval thresholds
            retrieval_thresholds = [
                "mean_recall_at_k",
                "mean_precision_at_k",
                "mrr",
                "mean_ndcg_at_k",
                "failed_query_fraction",
            ]
            for name in retrieval_thresholds:
                cfg_value = getattr(self.config, f"min_{name}", None)
                if cfg_value is not None or name == "failed_query_fraction":
                    warnings.append(
                        f"Retrieval threshold '{name}' is configured but no retrieval "
                        f"evaluation was run. Threshold skipped."
                    )
                skipped.append(name)

        # ---- Intent checks ----
        if report.intent is not None:
            intent = report.intent

            self._check_metric(
                name="intent_accuracy",
                actual=intent.accuracy,
                threshold=self.config.min_intent_accuracy,
                checked=checked,
                skipped=skipped,
                failures=failures,
            )

            # Macro F1: compute from per_class_metrics
            macro_f1 = self._compute_macro_f1(intent.per_class_metrics)
            checked["intent_macro_f1"] = macro_f1
            self._check_metric(
                name="intent_macro_f1",
                actual=macro_f1,
                threshold=self.config.min_intent_macro_f1,
                checked=checked,
                skipped=skipped,
                failures=failures,
            )

            # Intent failed-query fraction
            total_intent = intent.total_queries
            if total_intent > 0 and self.config.max_failed_query_fraction is not None:
                frac = intent.failed_queries / total_intent
                existing_key = "failed_query_fraction"
                # If retrieval was also checked, suffix intent
                key = "intent_failed_query_fraction" if existing_key in checked else existing_key
                checked[key] = frac
                if frac > self.config.max_failed_query_fraction:
                    failures.append(
                        ThresholdFailure(
                            metric=key,
                            actual=frac,
                            threshold=self.config.max_failed_query_fraction,
                            message=(
                                f"Intent failed query fraction {frac:.2%} exceeds maximum "
                                f"{self.config.max_failed_query_fraction:.2%}."
                            ),
                        )
                    )
        else:
            intent_thresholds = ["intent_accuracy", "intent_macro_f1"]
            for name in intent_thresholds:
                cfg_value = getattr(self.config, f"min_{name}", None)
                if cfg_value is not None:
                    warnings.append(
                        f"Intent threshold '{name}' is configured but no intent "
                        f"evaluation was run. Threshold skipped."
                    )
                skipped.append(name)

        return ThresholdResult(
            passed=len(failures) == 0,
            failures=failures,
            warnings=warnings,
            checked_metrics=checked,
            skipped_metrics=skipped,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _check_metric(
        name: str,
        actual: float,
        threshold: Optional[float],
        checked: Dict[str, Any],
        skipped: List[str],
        failures: List[ThresholdFailure],
    ) -> None:
        """Check a single metric against its threshold, mutating checked/skipped/failures."""
        if threshold is None:
            skipped.append(name)
            return
        checked[name] = actual
        if actual < threshold:
            failures.append(
                ThresholdFailure(
                    metric=name,
                    actual=actual,
                    threshold=threshold,
                    message=(
                        f"{name} = {actual:.4f} is below the configured minimum of {threshold:.4f}."
                    ),
                )
            )

    @staticmethod
    def _compute_macro_f1(per_class: Dict[str, Dict[str, float]]) -> float:
        """Compute macro-averaged F1 from per_class_metrics dict."""
        if not per_class:
            return 0.0
        f1_values = [cls_metrics.get("f1", 0.0) for cls_metrics in per_class.values()]
        return sum(f1_values) / len(f1_values) if f1_values else 0.0
