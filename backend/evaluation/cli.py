"""
evaluation/cli.py
Command-line interface for the RepoLens Evaluation Framework.
Provides commands to validate, inspect, convert, and run evaluation datasets.

Usage:
    python -m evaluation.cli validate <dataset_path> [--format json|jsonl] [--strict]
    python -m evaluation.cli inspect <dataset_path> [--format json|jsonl] [--sample N]
    python -m evaluation.cli convert <input_path> <output_path> [--format json|jsonl]
    python -m evaluation.cli evaluate <dataset_path> [--format json|jsonl] [--k K]
                                       [--retrieval-only] [--intent-only]
                                       [--output-json <path>]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import List, Optional

from app.core.logging import get_logger
from evaluation.config import get_evaluation_config
from evaluation.dataset import DatasetLoader, DatasetValidator
from evaluation.exceptions import DatasetLoadError, DatasetValidationError

logger = get_logger(__name__)



def create_parser() -> argparse.ArgumentParser:
    """Construct command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="python -m evaluation.cli",
        description="RepoLens AI Code Search Assistant - Evaluation CLI",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # --- validate ---
    val_parser = subparsers.add_parser(
        "validate", help="Validate an evaluation dataset against schema and business rules."
    )
    val_parser.add_argument("path", type=str, help="Path to evaluation dataset file (.json or .jsonl).")
    val_parser.add_argument(
        "--format",
        choices=["json", "jsonl", "auto"],
        default="auto",
        help="Dataset format (default: auto-detected from file extension).",
    )
    val_parser.add_argument(
        "--strict",
        action="store_true",
        default=True,
        help="Fail on any validation error (default: True).",
    )

    # --- inspect ---
    inspect_parser = subparsers.add_parser(
        "inspect", help="Inspect dataset metadata, statistics, and query samples."
    )
    inspect_parser.add_argument("path", type=str, help="Path to evaluation dataset file (.json or .jsonl).")
    inspect_parser.add_argument(
        "--format",
        choices=["json", "jsonl", "auto"],
        default="auto",
        help="Dataset format (default: auto-detected from file extension).",
    )
    inspect_parser.add_argument(
        "--sample",
        type=int,
        default=3,
        help="Number of query samples to display (default: 3).",
    )

    # --- convert ---
    conv_parser = subparsers.add_parser(
        "convert", help="Convert an evaluation dataset between JSON and JSONL formats."
    )
    conv_parser.add_argument("input_path", type=str, help="Path to input dataset file.")
    conv_parser.add_argument("output_path", type=str, help="Path to output dataset file.")
    conv_parser.add_argument(
        "--format",
        choices=["json", "jsonl"],
        default=None,
        help="Target format override (default: inferred from output extension).",
    )

    # --- evaluate ---
    eval_parser = subparsers.add_parser(
        "evaluate",
        help=(
            "Run retrieval and/or intent classification evaluation against a dataset "
            "using deterministic (offline) adapters."
        ),
    )
    eval_parser.add_argument("path", type=str, help="Path to evaluation dataset file (.json or .jsonl).")
    eval_parser.add_argument(
        "--format",
        choices=["json", "jsonl", "auto"],
        default="auto",
        help="Dataset format (default: auto-detected from file extension).",
    )
    eval_parser.add_argument(
        "--k",
        type=int,
        default=5,
        help="Rank cut-off K for retrieval metrics (default: 5).",
    )
    eval_parser.add_argument(
        "--retrieval-only",
        action="store_true",
        default=False,
        help="Run only retrieval evaluation (skip intent classification).",
    )
    eval_parser.add_argument(
        "--intent-only",
        action="store_true",
        default=False,
        help="Run only intent classification evaluation (skip retrieval).",
    )
    eval_parser.add_argument(
        "--output-json",
        type=str,
        default=None,
        help="Optional path to write the full JSON report to disk.",
    )
    eval_parser.add_argument(
        "--collection",
        type=str,
        default=None,
        help="Default Qdrant collection name for items without a collection_name field.",
    )

    # --- suite ---
    suite_parser = subparsers.add_parser(
        "suite",
        help=(
            "Execute the complete evaluation suite (Phase 3): load, validate, run, "
            "check thresholds, render Markdown report, and write versioned JSON result."
        ),
    )
    suite_parser.add_argument("path", type=str, help="Path to evaluation dataset file (.json or .jsonl).")
    suite_parser.add_argument(
        "--format",
        choices=["json", "jsonl", "auto"],
        default="auto",
        help="Dataset format (default: auto-detected from file extension).",
    )
    suite_parser.add_argument(
        "--k",
        type=int,
        default=5,
        help="Rank cut-off K for retrieval metrics (default: 5).",
    )
    suite_parser.add_argument(
        "--collection",
        type=str,
        default=None,
        help="Default Qdrant collection name for items without a collection_name field.",
    )
    suite_parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory to write versioned JSON result files (default: no file written).",
    )
    suite_parser.add_argument(
        "--offline",
        action="store_true",
        default=False,
        help="Run offline using deterministic fallback intent classifier (zero network calls).",
    )
    suite_parser.add_argument(
        "--output-md",
        "--save-markdown",
        dest="output_md",
        type=str,
        default=None,
        help="Optional path to write the Markdown report to disk.",
    )
    # Threshold flags
    suite_parser.add_argument(
        "--min-recall",
        "--min-recall-at-k",
        dest="min_recall",
        type=float,
        default=None,
        help="Minimum required mean Recall@K threshold (e.g. 0.6).",
    )
    suite_parser.add_argument(
        "--min-precision",
        "--min-precision-at-k",
        dest="min_precision",
        type=float,
        default=None,
        help="Minimum required mean Precision@K threshold.",
    )
    suite_parser.add_argument(
        "--min-mrr",
        type=float,
        default=None,
        help="Minimum required MRR threshold.",
    )
    suite_parser.add_argument(
        "--min-ndcg",
        "--min-ndcg-at-k",
        dest="min_ndcg",
        type=float,
        default=None,
        help="Minimum required mean nDCG@K threshold (only checked when nDCG is available).",
    )
    suite_parser.add_argument(
        "--min-accuracy",
        "--min-intent-accuracy",
        dest="min_accuracy",
        type=float,
        default=None,
        help="Minimum required intent classification accuracy (e.g. 0.75).",
    )
    suite_parser.add_argument(
        "--min-macro-f1",
        "--min-intent-macro-f1",
        dest="min_macro_f1",
        type=float,
        default=None,
        help="Minimum required macro-averaged intent F1.",
    )
    suite_parser.add_argument(
        "--max-failed-fraction",
        "--max-failed-query-fraction",
        dest="max_failed_fraction",
        type=float,
        default=None,
        help="Maximum allowed fraction of failed queries (e.g. 0.1 = 10%%).",
    )

    return parser




def run_validate(args: argparse.Namespace) -> int:
    """Validate dataset and report findings."""
    fmt = None if args.format == "auto" else args.format
    loader = DatasetLoader()

    print(f"\n[RepoLens Evaluation] Validating dataset: {args.path}")
    try:
        raw_items, _ = loader.load_raw_from_file(args.path, format=fmt)
    except DatasetLoadError as err:
        print(f"\n[ERROR] Failed to load dataset: {err}")
        return 1

    validator = DatasetValidator()
    result = validator.validate_raw_records(raw_items, strict=args.strict)

    print(f"\n=== Validation Summary ===")
    print(f"Total Items:            {result.total_items}")
    print(f"Queries with Chunks:    {result.queries_with_chunks}")
    print(f"Total Relevant Chunks:  {result.total_relevant_chunks}")
    print(f"Validation Status:      {'PASSED' if result.is_valid else 'FAILED'}")

    print("\n=== Intent Distribution ===")
    for intent, count in sorted(result.intent_distribution.items()):
        print(f"  - {intent:<20}: {count}")

    if result.warnings:
        print(f"\n=== Warnings ({len(result.warnings)}) ===")
        for w in result.warnings:
            print(f"  [WARN] {w}")

    if result.errors:
        print(f"\n=== Errors ({len(result.errors)}) ===")
        for err in result.errors:
            loc = f"index={err.item_index}" if err.item_index is not None else "dataset"
            qid = f" (query_id='{err.query_id}')" if err.query_id else ""
            print(f"  [ERROR] [{err.error_type}] {loc}{qid} field='{err.field}': {err.message}")
        return 1

    print("\n[SUCCESS] Dataset is valid and ready for benchmark evaluation.\n")
    return 0


def run_inspect(args: argparse.Namespace) -> int:
    """Inspect dataset contents and display statistics."""
    fmt = None if args.format == "auto" else args.format
    loader = DatasetLoader()

    try:
        dataset = loader.load_from_file(args.path, format=fmt, validate=True, strict=False)
    except (DatasetLoadError, DatasetValidationError) as err:
        print(f"\n[ERROR] Failed to read dataset: {err}")
        return 1

    print(f"\n=== Dataset Inspection: {dataset.dataset_name} ===")
    print(f"Version:     {dataset.version}")
    print(f"Description: {dataset.description or 'N/A'}")
    print(f"Total Items: {len(dataset)}")

    validator = DatasetValidator()
    res = validator.validate(dataset, strict=False)

    print("\n=== Intent Breakdown ===")
    for intent, count in sorted(res.intent_distribution.items()):
        print(f"  - {intent:<20}: {count}")

    sample_count = min(args.sample, len(dataset))
    if sample_count > 0:
        print(f"\n=== Sample Items ({sample_count} of {len(dataset)}) ===")
        for i in range(sample_count):
            item = dataset[i]
            print(f"\n[{i+1}] ID: {item.query_id}")
            print(f"    Query:   \"{item.query}\"")
            print(f"    Intent:  {item.expected_intent.value}")
            print(f"    Repo:    {item.repository or 'None'}")
            print(f"    Chunks:  {len(item.expected_chunks)} relevant chunk(s)")

    print()
    return 0


def run_convert(args: argparse.Namespace) -> int:
    """Convert dataset to another format."""
    loader = DatasetLoader()
    try:
        dataset = loader.load_from_file(args.input_path, validate=True, strict=True)
    except Exception as err:
        print(f"\n[ERROR] Failed to load input dataset: {err}")
        return 1

    try:
        loader.save_to_file(dataset, args.output_path, format=args.format)
        print(f"[SUCCESS] Converted {len(dataset)} items to: {args.output_path}")
        return 0
    except Exception as err:
        print(f"\n[ERROR] Failed to save converted dataset: {err}")
        return 1


def run_evaluate(args: argparse.Namespace) -> int:
    """Run evaluation and print a summary report."""
    from evaluation.adapters.intent_adapter import ProductionIntentAdapter
    from evaluation.runner import EvaluationRunner

    fmt = None if args.format == "auto" else args.format
    loader = DatasetLoader()

    try:
        dataset = loader.load_from_file(args.path, format=fmt, validate=True, strict=True)
    except (DatasetLoadError, DatasetValidationError) as err:
        print(f"\n[ERROR] Failed to load dataset: {err}")
        return 1

    retrieval_only = getattr(args, "retrieval_only", False)
    intent_only = getattr(args, "intent_only", False)

    # Determine which adapters to use
    # Retrieval: not available in offline/deterministic mode (requires live Qdrant).
    # When --intent-only is set, skip retrieval adapter entirely.
    retriever_adapter = None
    if not intent_only:
        # Retrieval evaluation requires a live Qdrant collection; inform the user.
        print(
            "\n[INFO] Retrieval evaluation requires a live Qdrant connection. "
            "To run retrieval evaluation, call EvaluationRunner programmatically "
            "with a ProductionRetrieverAdapter backed by a real CodeRetrievalStage.\n"
            "Proceeding with intent-only evaluation in this CLI session.\n"
        )

    # Intent: always use deterministic offline adapter in CLI mode
    intent_adapter = None
    if not retrieval_only:
        intent_adapter = ProductionIntentAdapter(deterministic_only=True)

    if retriever_adapter is None and intent_adapter is None:
        print("\n[ERROR] No evaluation adapter available. Use --intent-only for offline evaluation.")
        return 1

    try:
        runner = EvaluationRunner(
            retriever_adapter=retriever_adapter,
            intent_adapter=intent_adapter,
        )
        report = asyncio.run(
            runner.run(
                dataset,
                k=args.k,
                default_collection=getattr(args, "collection", None),
            )
        )
    except Exception as err:
        print(f"\n[ERROR] Evaluation run failed: {err}")
        return 1

    # Print summary
    summary = report.to_summary_dict()
    import json
    print("\n=== Evaluation Report Summary ===")
    print(json.dumps(summary, indent=2))

    # Optionally save full report
    output_json = getattr(args, "output_json", None)
    if output_json:
        out_path = Path(output_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report.to_json(), encoding="utf-8")
        print(f"\n[SUCCESS] Full report written to: {out_path}")

    if report.intent and report.intent.accuracy < 0.5:
        print("\n[WARN] Intent classification accuracy is below 50%.")

    return 0


def run_suite(args: argparse.Namespace) -> int:
    """Execute the complete Phase 3 evaluation suite."""
    from evaluation.adapters.intent_adapter import ProductionIntentAdapter
    from evaluation.reporting import OUTCOME_BLOCKED, OUTCOME_BELOW_THRESHOLD
    from evaluation.suite import EvaluationSuite
    from evaluation.thresholds import ThresholdConfig

    # Build threshold config from CLI flags (all optional)
    any_threshold = any([
        args.min_recall, args.min_precision, args.min_mrr, args.min_ndcg,
        args.min_accuracy, args.min_macro_f1, args.max_failed_fraction,
    ])
    thresholds = ThresholdConfig(
        min_recall_at_k=args.min_recall,
        min_precision_at_k=args.min_precision,
        min_mrr=args.min_mrr,
        min_ndcg_at_k=args.min_ndcg,
        min_intent_accuracy=args.min_accuracy,
        min_intent_macro_f1=args.min_macro_f1,
        max_failed_query_fraction=args.max_failed_fraction,
    ) if any_threshold else None

    output_dir = Path(args.output_dir) if getattr(args, "output_dir", None) else None

    # Offline CLI only supports deterministic intent adapter
    intent_adapter = ProductionIntentAdapter(deterministic_only=True)

    suite = EvaluationSuite(
        dataset_path=args.path,
        intent_adapter=intent_adapter,
        thresholds=thresholds,
        output_dir=output_dir,
        k=args.k,
        default_collection=getattr(args, "collection", None),
    )

    outcome = asyncio.run(suite.run())

    # Print Markdown report to stdout
    print(outcome.markdown_report)

    # Optionally save Markdown to disk
    md_path = getattr(args, "output_md", None)
    if md_path:
        out = Path(md_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(outcome.markdown_report, encoding="utf-8")
        print(f"\n[SUCCESS] Markdown report written to: {out}")

    if outcome.json_report_path:
        print(f"[SUCCESS] Versioned JSON report written to: {outcome.json_report_path}")

    if outcome.warnings:
        for w in outcome.warnings:
            print(f"[WARN] {w}")

    # Exit codes:
    #   0 = SUCCESS or COMPLETED_WITH_FAILURES (evaluation ran; caller decides what to do)
    #   1 = BLOCKED (could not run at all) or BELOW_THRESHOLD (explicit threshold failure)
    if outcome.outcome_code in (OUTCOME_BLOCKED, OUTCOME_BELOW_THRESHOLD):
        return 1
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """Main CLI entry point."""
    parser = create_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    if args.command == "validate":
        return run_validate(args)
    elif args.command == "inspect":
        return run_inspect(args)
    elif args.command == "convert":
        return run_convert(args)
    elif args.command == "evaluate":
        return run_evaluate(args)
    elif args.command == "suite":
        return run_suite(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())


