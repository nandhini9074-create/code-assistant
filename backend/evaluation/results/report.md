# RepoLens Evaluation Report ✅

> **Outcome:** `SUCCESS`
> **Dataset:** RepoLens-Sample-Evaluation-Benchmark
> **Generated:** 2026-10-21T08:13:46.018484+00:00

## Run Configuration

| Parameter          | Value |
|:-------------------|:------|
| Rank cut-off K     | N/A   |
| Schema version     | 3.0 |
| dataset_path       | evaluation\datasets\sample_evaluation_dataset.json |
| k                  | 5 |
| thresholds_configured | False |

## Dataset Health

### Intent

| Metric              | Count |
|:--------------------|------:|
| Total queries       | 6 |
| Evaluated           | 6 |
| Skipped             | 0 |
| Failed (adapter error) | 0 |

## Intent Classification Metrics

| Metric        | Score  |
|:--------------|-------:|
| Accuracy      | 0.8333 |
| Macro F1      | 0.8333 |

### Per-class Breakdown

| Intent              | Precision | Recall | F1     | Support |
|:--------------------|----------:|-------:|-------:|--------:|
| ADD_FEATURE         |    1.0000 | 1.0000 | 1.0000 |       1 |
| FIX_BUG             |    1.0000 | 1.0000 | 1.0000 |       1 |
| FIX_VULNERABILITY   |    1.0000 | 1.0000 | 1.0000 |       1 |
| OPTIMIZE            |    0.0000 | 0.0000 | 0.0000 |       1 |
| REFACTOR            |    1.0000 | 1.0000 | 1.0000 |       1 |
| RETRIEVE            |    1.0000 | 1.0000 | 1.0000 |       1 |

### Confusion Matrix

| True \ Predicted | ADD_FEATUR | FIX_BUG | FIX_VULNER | OPTIMIZE | REFACTOR | RETRIEVE | __none__ |
|:---|---:|---:|---:|---:|---:|---:|---:|
| ADD_FEATURE       | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| FIX_BUG           | 0 | 1 | 0 | 0 | 0 | 0 | 0 |
| FIX_VULNERABILITY | 0 | 0 | 1 | 0 | 0 | 0 | 0 |
| OPTIMIZE          | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| REFACTOR          | 0 | 0 | 0 | 0 | 1 | 0 | 0 |
| RETRIEVE          | 0 | 0 | 0 | 0 | 0 | 1 | 0 |
| __none__          | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## How to Add New Evaluation Queries

1. Open `evaluation/datasets/sample_evaluation_dataset.json` (or your custom dataset file).
2. Add a new entry to the `items` array:
   ```json
   {
     "query_id": "eval-q07",
     "query": "Your natural language query here",
     "expected_intent": "RETRIEVE",
     "repository": "your-repo-name",
     "collection_name": "qdrant_collection_name",
     "expected_chunks": [
       {"chunk_id": "chunk_hash_value", "relevance_grade": 3.0,
        "file_path": "path/to/file.py", "symbol_name": "FunctionName"}
     ]
   }
   ```
3. **Ground-truth chunk IDs**: retrieve the `chunk_hash` from Qdrant by running a search
   and inspecting the payload of the most relevant point.
4. **Relevance grades**: use the 0–4 scale:
   - 4 = perfectly relevant (the exact answer)
   - 3 = highly relevant
   - 2 = partially relevant
   - 1 = marginally relevant
   - 0 = not relevant (omit from expected_chunks)
5. **Verify ground-truth**: manually confirm that each listed chunk actually
   addresses the query.  Use `python -m evaluation.cli inspect <dataset>` to review.
6. **Run validation**: `python -m evaluation.cli validate <dataset>` before committing.
7. **Incompatible datasets**: when comparing results across runs, ensure both used
   the same dataset version.  Warn explicitly when `dataset_name` or `version` differ.

## Known Limitations

- Retrieval evaluation requires a **live Qdrant connection**.  Offline CLI mode
  runs intent-only evaluation using the deterministic fallback classifier.
- Chunk IDs in `expected_chunks` must match the **exact `chunk_hash`** stored in
  Qdrant.  Stale IDs after re-indexing will cause false negatives.
- nDCG is only computed when at least one chunk has a relevance grade != 1.0
  (binary-relevance datasets report nDCG as N/A).
- Thresholds are project configuration and should be reviewed alongside dataset
  size and coverage before interpreting pass/fail as a quality signal.

