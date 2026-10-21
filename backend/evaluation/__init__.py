"""
evaluation
Evaluation Framework for RepoLens AI Code Search Assistant.
Provides dataset schemas, validation, loaders, adapters, metrics, evaluation runner,
thresholds, reporting, and the complete evaluation suite.
"""

from evaluation.config import EvaluationConfig, get_evaluation_config
from evaluation.dataset import DatasetLoader, DatasetValidator
from evaluation.exceptions import (
    AdapterError,
    DatasetLoadError,
    DatasetValidationError,
    EvaluationError,
)
from evaluation.metrics import (
    intent_accuracy,
    intent_confusion_matrix,
    mean_metric,
    mean_reciprocal_rank,
    ndcg_at_k,
    per_class_intent_metrics,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from evaluation.results import (
    EvaluationReport,
    IntentEvaluationReport,
    QueryIntentResult,
    QueryRetrievalResult,
    RetrievalEvaluationReport,
)
from evaluation.runner import EvaluationRunner
from evaluation.reporting import (
    OUTCOME_BLOCKED,
    OUTCOME_FAILURES,
    OUTCOME_BELOW_THRESHOLD,
    OUTCOME_SUCCESS,
    MarkdownReportRenderer,
    VersionedJsonWriter,
)
from evaluation.schemas import (
    EvaluationDataset,
    EvaluationItem,
    RelevanceGrade,
    RelevantChunk,
    ValidationErrorDetail,
    ValidationResult,
)
from evaluation.suite import EvaluationSuite, SuiteOutcome
from evaluation.thresholds import (
    ThresholdChecker,
    ThresholdConfig,
    ThresholdFailure,
    ThresholdResult,
)

__all__ = [
    # exceptions
    "AdapterError",
    "DatasetLoadError",
    "DatasetValidationError",
    "EvaluationError",
    # config
    "EvaluationConfig",
    "get_evaluation_config",
    # dataset
    "DatasetLoader",
    "DatasetValidator",
    # schemas
    "EvaluationDataset",
    "EvaluationItem",
    "RelevanceGrade",
    "RelevantChunk",
    "ValidationErrorDetail",
    "ValidationResult",
    # metrics
    "intent_accuracy",
    "intent_confusion_matrix",
    "mean_metric",
    "mean_reciprocal_rank",
    "ndcg_at_k",
    "per_class_intent_metrics",
    "precision_at_k",
    "recall_at_k",
    "reciprocal_rank",
    # results
    "EvaluationReport",
    "IntentEvaluationReport",
    "QueryIntentResult",
    "QueryRetrievalResult",
    "RetrievalEvaluationReport",
    # runner
    "EvaluationRunner",
    # reporting
    "OUTCOME_BLOCKED",
    "OUTCOME_BELOW_THRESHOLD",
    "OUTCOME_FAILURES",
    "OUTCOME_SUCCESS",
    "MarkdownReportRenderer",
    "VersionedJsonWriter",
    # suite
    "EvaluationSuite",
    "SuiteOutcome",
    # thresholds
    "ThresholdChecker",
    "ThresholdConfig",
    "ThresholdFailure",
    "ThresholdResult",
]

