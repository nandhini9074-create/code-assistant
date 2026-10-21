# RepoLens Evaluation Framework

Standalone evaluation module for benchmarking intent classification and code retrieval performance.

For comprehensive documentation, see [docs/17_evaluation_framework.md](../docs/17_evaluation_framework.md).

## Quick Commands

### Run Full Suite (Phase 3 Orchestrator)
```bash
# Offline (deterministic classifier, no network calls)
python -m evaluation.cli suite evaluation/datasets/sample_evaluation_dataset.json --offline

# With acceptance thresholds
python -m evaluation.cli suite evaluation/datasets/sample_evaluation_dataset.json \
    --offline \
    --min-intent-accuracy 0.70 \
    --output-dir evaluation/results \
    --save-markdown evaluation/results/report.md
```

### Validate Dataset (Phase 1)
```bash
python -m evaluation.cli validate evaluation/datasets/sample_evaluation_dataset.json
```

### Inspect Dataset (Phase 1)
```bash
python -m evaluation.cli inspect evaluation/datasets/sample_evaluation_dataset.json
```

### Run Benchmarks Directly (Phase 2 Runner)
```bash
python -m evaluation.cli run evaluation/datasets/sample_evaluation_dataset.json --intent-only --offline
```
