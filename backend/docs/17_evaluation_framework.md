# RepoLens Evaluation Framework (Phase 1–3)

This document provides a comprehensive guide for running, configuring, and extending the evaluation framework for the RepoLens AI Code Search Assistant.

---

## 1. Overview and Architecture

The evaluation framework lives entirely in `backend/evaluation/` as an isolated, standalone module. It **does not modify** any production search pipelines, ingestion workers, database schemas, or API endpoints.

```
backend/evaluation/
├── adapters/                  # Non-intrusive adapters wrapping production components
│   ├── base.py                # Abstract BaseIntentAdapter, BaseRetrieverAdapter
│   ├── intent_adapter.py      # ProductionIntentAdapter (supports offline/deterministic mode)
│   └── retriever_adapter.py   # ProductionRetrieverAdapter (delegates to HybridSearch)
├── datasets/                  # Ground-truth evaluation benchmarks (.json / .jsonl)
│   └── sample_evaluation_dataset.json
├── dataset.py                 # DatasetLoader and schema validation logic
├── schemas.py                 # Pydantic schemas (EvaluationDataset, EvaluationItem, etc.)
├── metrics.py                 # Core evaluation metrics (Recall@K, Precision@K, MRR, nDCG@K, accuracy, F1)
├── results.py                 # Typed result containers (QueryRetrievalResult, EvaluationReport, etc.)
├── runner.py                  # EvaluationRunner (executes retrieval & intent benchmarks)
├── thresholds.py              # ThresholdConfig & ThresholdChecker (project acceptance criteria)
├── reporting.py               # MarkdownReportRenderer & VersionedJsonWriter
├── suite.py                   # Single-command orchestrator (EvaluationSuite)
└── cli.py                     # CLI entry points (suite, run, validate, inspect, generate-template)
```

---

## 2. Quickstart: Single-Command Evaluation Suite

Execute the complete Phase 3 evaluation pipeline (load → validate → benchmark → check thresholds → render Markdown → write versioned JSON) in a single command:

```bash
# Offline mode (deterministic intent classification, zero external network calls)
python -m evaluation.cli suite evaluation/datasets/sample_evaluation_dataset.json --offline

# With custom acceptance thresholds
python -m evaluation.cli suite evaluation/datasets/sample_evaluation_dataset.json \
    --offline \
    --min-intent-accuracy 0.70 \
    --min-intent-macro-f1 0.65

# Full live evaluation (with live Qdrant vector database)
python -m evaluation.cli suite evaluation/datasets/sample_evaluation_dataset.json \
    --min-recall-at-k 0.60 \
    --min-mrr 0.50 \
    --min-intent-accuracy 0.75 \
    --output-dir evaluation/results \
    --save-markdown evaluation/results/latest_report.md
```

### Exit Codes
- `0`: Evaluation finished and all configured thresholds passed (`SUCCESS` or `COMPLETED_WITH_FAILURES` when thresholds met).
- `1`: Evaluation failed acceptance criteria (`BELOW_THRESHOLD`) or could not run (`BLOCKED`).

---

## 3. Outcome Classifications

The suite categorizes runs into four distinct outcomes:

| Outcome Code | Meaning | CLI Exit Code |
|:---|:---|:---:|
| `SUCCESS` | All configured thresholds passed and no adapter errors occurred. | `0` |
| `COMPLETED_WITH_FAILURES` | Adapter or query errors occurred during evaluation, but thresholds either passed or were not configured. | `0` |
| `BELOW_THRESHOLD` | Evaluation completed, but one or more metrics failed configured acceptance criteria. | `1` |
| `BLOCKED` | Evaluation could not execute (e.g., missing dataset, missing required dependencies, no adapters provided). | `1` |

---

## 4. How to Add New Evaluation Queries

### Dataset Format
Datasets are stored as JSON or JSONL files. Each entry represents an evaluation item conforming to the `EvaluationItem` schema:

```json
{
  "query_id": "eval_001",
  "query": "Where is JWT authentication verified in incoming requests?",
  "expected_intent": "RETRIEVE",
  "collection_name": "repolens-core",
  "expected_chunks": [
    {
      "chunk_id": "chunk_auth_middleware_01",
      "relevance_grade": 4
    },
    {
      "chunk_id": "chunk_token_validator_02",
      "relevance_grade": 3
    }
  ],
  "description": "Verifies retrieval of JWT middleware and token verification logic."
}
```

### Supported Intents
The evaluation dataset supports the six canonical RepoLens intents:
- `RETRIEVE`: Search and locate existing code or documentation.
- `ADD_FEATURE`: Add new functionality or endpoints.
- `FIX_BUG`: Debug and fix broken behavior.
- `OPTIMIZE`: Performance improvements, caching, or query optimization.
- `REFACTOR`: Clean code, rename, restructure without behavioral change.
- `FIX_VULNERABILITY`: Security patches, CVE remediation, sanitization.

### Relevance Grading Guidelines (0 to 4 Scale)
- **4 (Perfect)**: Exact primary target chunk that directly answers or implements the solution.
- **3 (Highly Relevant)**: Directly supporting chunk with essential context.
- **2 (Partially Relevant)**: Related code (e.g., caller or interface definition) that helps but is not central.
- **1 (Marginally Relevant)**: Weak topical relevance.
- **0 (Not Relevant)**: Do not include in `expected_chunks`.

### Validating New Datasets
Always validate your dataset before running evaluation benchmarks:
```bash
python -m evaluation.cli validate path/to/your_dataset.json
```
The validator checks for:
- Required fields (`query_id`, `query`, `expected_intent`).
- Valid enum values for `expected_intent`.
- Duplicate query IDs.
- Valid relevance grades (0.0 to 4.0).
- Consistent collection identifiers.

---

## 5. Adjusting Acceptance Thresholds

Thresholds are treated as **project configuration**, not absolute performance guarantees. Configure them based on project goals, dataset maturity, and retrieval environment:

### Configurable Thresholds:
- `--min-recall-at-k`: Minimum required Recall@5 (e.g., `0.60`).
- `--min-precision-at-k`: Minimum required Precision@5 (e.g., `0.30`).
- `--min-mrr`: Minimum Mean Reciprocal Rank (e.g., `0.50`).
- `--min-ndcg-at-k`: Minimum nDCG@5 (requires graded relevance labels).
- `--min-intent-accuracy`: Minimum overall intent classification accuracy (e.g., `0.75`).
- `--min-intent-macro-f1`: Minimum macro-averaged F1 across all intent classes.
- `--max-failed-query-fraction`: Maximum allowed fraction of queries experiencing errors (e.g., `0.05` for 5%).

### Programmatic Usage
```python
from evaluation.suite import EvaluationSuite
from evaluation.thresholds import ThresholdConfig
from evaluation.adapters.intent_adapter import ProductionIntentAdapter

suite = EvaluationSuite(
    dataset_path="evaluation/datasets/sample_evaluation_dataset.json",
    intent_adapter=ProductionIntentAdapter(deterministic_only=True),
    thresholds=ThresholdConfig(
        min_intent_accuracy=0.75,
        min_intent_macro_f1=0.70,
        max_failed_query_fraction=0.0,
    ),
    output_dir="evaluation/results",
)
outcome = await suite.run()
```

---

## 6. Interpreting Evaluation Reports

### Markdown Report
Generated Markdown reports include:
1. **Header & Outcome**: Run status badge (`SUCCESS`, `BELOW_THRESHOLD`, etc.) and timestamp.
2. **Dataset Health**: Total items, evaluated queries, skipped queries, and failure breakdown.
3. **Retrieval Metrics Table**: Recall@K, Precision@K, MRR, and nDCG@K.
4. **Intent Classification Table**: Overall accuracy, macro-F1, per-class precision/recall/F1/support, and confusion matrix.
5. **Threshold Check Results**: Status of each checked metric against configured minimums with clear failure diagnostics.
6. **Troubleshooting & Known Limitations**: Live Qdrant requirements, chunk hash matching notes, and offline guidance.

### Versioned JSON Artifacts
Results written to disk are named with the schema version and UTC timestamp:
`evaluation/results/<dataset_slug>_v3.0_<YYYYMMDDTHHMMSSZ>.json`

Structure:
```json
{
  "schema_version": "3.0",
  "outcome": "SUCCESS",
  "generated_at": "20261021T120000Z",
  "evaluation": { ... },
  "threshold_check": {
    "passed": true,
    "failures": [],
    "warnings": [],
    "checked_metrics": { ... }
  },
  "metadata": { ... }
}
```
Use these versioned JSON records in CI/CD pipelines to track regression trends over time.
