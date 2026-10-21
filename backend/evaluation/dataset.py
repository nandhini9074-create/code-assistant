"""
evaluation/dataset.py
Dataset loader and validator for the RepoLens Evaluation Framework.
Supports reading and writing JSON and JSONL datasets with comprehensive validation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from app.core.enums import IntentType
from app.core.logging import get_logger
from evaluation.config import (
    SUPPORTED_INTENT_VALUES,
    EvaluationConfig,
    get_evaluation_config,
)
from evaluation.exceptions import (
    DatasetLoadError,
    DatasetValidationError,
)
from evaluation.schemas import (
    EvaluationDataset,
    EvaluationItem,
    RelevantChunk,
    ValidationErrorDetail,
    ValidationResult,
)

logger = get_logger(__name__)


class DatasetValidator:
    """
    Validates evaluation datasets against required fields, valid intents,
    unique IDs, and valid relevance grades.
    """

    def __init__(self, config: Optional[EvaluationConfig] = None) -> None:
        self.config = config or get_evaluation_config()

    def validate_raw_records(
        self, records: List[Dict[str, Any]], strict: bool = True
    ) -> ValidationResult:
        """
        Validate raw parsed records (dictionaries) before constructing full EvaluationDataset models.
        Collects all validation errors across all records.
        """
        errors: List[ValidationErrorDetail] = []
        warnings: List[str] = []
        seen_query_ids: Set[str] = set()
        intent_distribution: Dict[str, int] = {intent: 0 for intent in sorted(SUPPORTED_INTENT_VALUES)}
        queries_with_chunks = 0
        total_relevant_chunks = 0

        for index, record in enumerate(records):
            if not isinstance(record, dict):
                errors.append(
                    ValidationErrorDetail(
                        item_index=index,
                        query_id=None,
                        field="root",
                        error_type="INVALID_RECORD_TYPE",
                        message=f"Record at index {index} must be a dictionary, got {type(record).__name__}.",
                    )
                )
                continue

            query_id = record.get("query_id")
            query = record.get("query")
            intent = record.get("expected_intent")

            # 1. Missing / invalid query_id
            if query_id is None:
                errors.append(
                    ValidationErrorDetail(
                        item_index=index,
                        query_id=None,
                        field="query_id",
                        error_type="MISSING_FIELD",
                        message=f"Item at index {index} is missing mandatory field 'query_id'.",
                    )
                )
            elif not isinstance(query_id, str) or not query_id.strip():
                errors.append(
                    ValidationErrorDetail(
                        item_index=index,
                        query_id=str(query_id),
                        field="query_id",
                        error_type="INVALID_FIELD",
                        message=f"Item at index {index} has empty or non-string 'query_id'.",
                    )
                )
            else:
                clean_query_id = query_id.strip()
                # 2. Duplicate query_id check
                if clean_query_id in seen_query_ids:
                    errors.append(
                        ValidationErrorDetail(
                            item_index=index,
                            query_id=clean_query_id,
                            field="query_id",
                            error_type="DUPLICATE_QUERY_ID",
                            message=f"Duplicate query_id '{clean_query_id}' found at index {index}.",
                        )
                    )
                else:
                    seen_query_ids.add(clean_query_id)

            # 3. Missing / invalid query text
            if query is None:
                errors.append(
                    ValidationErrorDetail(
                        item_index=index,
                        query_id=str(query_id) if query_id else None,
                        field="query",
                        error_type="MISSING_FIELD",
                        message=f"Item at index {index} is missing mandatory field 'query'.",
                    )
                )
            elif not isinstance(query, str) or not query.strip():
                errors.append(
                    ValidationErrorDetail(
                        item_index=index,
                        query_id=str(query_id) if query_id else None,
                        field="query",
                        error_type="INVALID_FIELD",
                        message=f"Item at index {index} has empty or non-string 'query' text.",
                    )
                )

            # 4. Missing / invalid expected_intent
            if intent is None:
                errors.append(
                    ValidationErrorDetail(
                        item_index=index,
                        query_id=str(query_id) if query_id else None,
                        field="expected_intent",
                        error_type="MISSING_FIELD",
                        message=f"Item at index {index} is missing mandatory field 'expected_intent'.",
                    )
                )
            else:
                intent_str = intent.value if hasattr(intent, "value") else str(intent).strip().upper()
                if intent_str not in SUPPORTED_INTENT_VALUES:
                    allowed = sorted(SUPPORTED_INTENT_VALUES)
                    errors.append(
                        ValidationErrorDetail(
                            item_index=index,
                            query_id=str(query_id) if query_id else None,
                            field="expected_intent",
                            error_type="INVALID_INTENT",
                            message=f"Item at index {index} has invalid intent '{intent}'. Allowed intents are: {allowed}.",
                        )
                    )
                else:
                    intent_distribution[intent_str] = intent_distribution.get(intent_str, 0) + 1

            # 5. Validate relevance labels and chunks if present
            expected_chunks = record.get("expected_chunks")
            if expected_chunks:
                item_chunk_errors, chunk_count = self._validate_raw_chunks(
                    expected_chunks, index=index, query_id=str(query_id) if query_id else None
                )
                errors.extend(item_chunk_errors)
                if chunk_count > 0:
                    queries_with_chunks += 1
                    total_relevant_chunks += chunk_count
            elif expected_chunks is not None and not isinstance(expected_chunks, (list, dict)):
                errors.append(
                    ValidationErrorDetail(
                        item_index=index,
                        query_id=str(query_id) if query_id else None,
                        field="expected_chunks",
                        error_type="INVALID_CHUNKS_TYPE",
                        message=f"Item at index {index} 'expected_chunks' must be a list or dict, got {type(expected_chunks).__name__}.",
                    )
                )

        is_valid = len(errors) == 0

        # General dataset warnings
        if len(records) > 0 and queries_with_chunks == 0:
            warnings.append("Dataset does not contain expected relevant chunks for any query (retrieval evaluation will be unavailable).")

        unused_intents = [it for it, count in intent_distribution.items() if count == 0]
        if unused_intents and len(records) >= 6:
            warnings.append(f"The following supported intents are not represented in this dataset: {unused_intents}.")

        result = ValidationResult(
            is_valid=is_valid,
            total_items=len(records),
            errors=errors,
            warnings=warnings,
            intent_distribution=intent_distribution,
            queries_with_chunks=queries_with_chunks,
            total_relevant_chunks=total_relevant_chunks,
        )

        logger.info(
            "dataset_validation_completed",
            is_valid=is_valid,
            total_items=len(records),
            error_count=len(errors),
            warning_count=len(warnings),
        )

        return result

    def _validate_raw_chunks(
        self, chunks_raw: Any, index: int, query_id: Optional[str]
    ) -> Tuple[List[ValidationErrorDetail], int]:
        """Validate raw chunk entries for missing chunk_ids or invalid relevance labels."""
        errors: List[ValidationErrorDetail] = []
        count = 0

        if isinstance(chunks_raw, dict):
            # Dict of {chunk_id: grade}
            for cid, grade in chunks_raw.items():
                count += 1
                if not isinstance(cid, str) or not cid.strip():
                    errors.append(
                        ValidationErrorDetail(
                            item_index=index,
                            query_id=query_id,
                            field="expected_chunks",
                            error_type="INVALID_CHUNK_ID",
                            message=f"Item at index {index} has invalid or empty chunk_id key: '{cid}'.",
                        )
                    )
                grade_err = self._validate_grade_value(grade, index, query_id, chunk_id=str(cid))
                if grade_err:
                    errors.append(grade_err)
            return errors, count

        if isinstance(chunks_raw, list):
            for c_idx, chunk_item in enumerate(chunks_raw):
                count += 1
                if isinstance(chunk_item, str):
                    if not chunk_item.strip():
                        errors.append(
                            ValidationErrorDetail(
                                item_index=index,
                                query_id=query_id,
                                field=f"expected_chunks[{c_idx}]",
                                error_type="INVALID_CHUNK_ID",
                                message=f"Item at index {index} has empty chunk string at chunk position {c_idx}.",
                            )
                        )
                elif isinstance(chunk_item, dict):
                    cid = chunk_item.get("chunk_id")
                    file_path = chunk_item.get("file_path")
                    has_cid = isinstance(cid, str) and bool(cid.strip())
                    has_fp = isinstance(file_path, str) and bool(file_path.strip())

                    if not has_cid and not has_fp:
                        errors.append(
                            ValidationErrorDetail(
                                item_index=index,
                                query_id=query_id,
                                field=f"expected_chunks[{c_idx}]",
                                error_type="INVALID_CHUNK_ID",
                                message=(
                                    f"Item at index {index} has invalid or missing 'chunk_id' or 'file_path' "
                                    f"at chunk position {c_idx}."
                                ),
                            )
                        )
                    grade = chunk_item.get("relevance_grade")
                    if grade is None:
                        errors.append(
                            ValidationErrorDetail(
                                item_index=index,
                                query_id=query_id,
                                field=f"expected_chunks[{c_idx}].relevance_grade",
                                error_type="MISSING_RELEVANCE_GRADE",
                                message=f"Item at index {index} is missing mandatory 'relevance_grade' at chunk position {c_idx}.",
                            )
                        )
                    else:
                        chunk_ref = cid if has_cid else (file_path if has_fp else str(c_idx))
                        grade_err = self._validate_grade_value(
                            grade, index, query_id, chunk_id=str(chunk_ref)
                        )
                        if grade_err:
                            errors.append(grade_err)
                elif isinstance(chunk_item, RelevantChunk):
                    # Already a schema instance; check range
                    chunk_ref = chunk_item.identifier
                    grade_err = self._validate_grade_value(
                        chunk_item.relevance_grade, index, query_id, chunk_id=chunk_ref
                    )
                    if grade_err:
                        errors.append(grade_err)
                else:
                    errors.append(
                        ValidationErrorDetail(
                            item_index=index,
                            query_id=query_id,
                            field=f"expected_chunks[{c_idx}]",
                            error_type="INVALID_CHUNK_TYPE",
                            message=f"Item at index {index} has unsupported chunk entry type {type(chunk_item).__name__} at position {c_idx}.",
                        )
                    )
            return errors, count

        errors.append(
            ValidationErrorDetail(
                item_index=index,
                query_id=query_id,
                field="expected_chunks",
                error_type="INVALID_CHUNKS_TYPE",
                message=f"Item at index {index} 'expected_chunks' must be a list or dict, got {type(chunks_raw).__name__}.",
            )
        )
        return errors, 0

    def _validate_grade_value(
        self, grade: Any, index: int, query_id: Optional[str], chunk_id: str
    ) -> Optional[ValidationErrorDetail]:
        """Validate that a relevance grade is numeric and non-negative."""
        try:
            numeric_val = float(grade)
        except (TypeError, ValueError):
            return ValidationErrorDetail(
                item_index=index,
                query_id=query_id,
                field="expected_chunks.relevance_grade",
                error_type="INVALID_RELEVANCE_GRADE",
                message=f"Item at index {index} chunk '{chunk_id}' has non-numeric relevance grade '{grade}'.",
            )

        if numeric_val < self.config.min_relevance_grade:
            return ValidationErrorDetail(
                item_index=index,
                query_id=query_id,
                field="expected_chunks.relevance_grade",
                error_type="INVALID_RELEVANCE_GRADE",
                message=f"Item at index {index} chunk '{chunk_id}' has negative relevance grade {numeric_val} (min allowed: {self.config.min_relevance_grade}).",
            )

        if numeric_val > self.config.max_relevance_grade:
            return ValidationErrorDetail(
                item_index=index,
                query_id=query_id,
                field="expected_chunks.relevance_grade",
                error_type="INVALID_RELEVANCE_GRADE",
                message=f"Item at index {index} chunk '{chunk_id}' has relevance grade {numeric_val} exceeding max allowed {self.config.max_relevance_grade}.",
            )

        return None

    def validate(
        self, dataset: EvaluationDataset, strict: bool = True
    ) -> ValidationResult:
        """Validate an already instantiated EvaluationDataset."""
        raw_items = [item.model_dump(mode="json") for item in dataset.items]
        return self.validate_raw_records(raw_items, strict=strict)


class DatasetLoader:
    """
    Loads, deserializes, and validates evaluation datasets from JSON, JSONL,
    strings, and files.
    """

    def __init__(
        self,
        validator: Optional[DatasetValidator] = None,
        config: Optional[EvaluationConfig] = None,
    ) -> None:
        self.config = config or get_evaluation_config()
        self.validator = validator or DatasetValidator(self.config)


    def load_raw_from_file(
        self,
        file_path: Union[str, Path],
        format: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Read and parse raw JSON/JSONL records and metadata from disk without model construction."""
        path = Path(file_path).resolve()
        if not path.exists():
            raise DatasetLoadError(f"Dataset file not found: {path}", file_path=str(path))
        if not path.is_file():
            raise DatasetLoadError(f"Dataset path is not a file: {path}", file_path=str(path))

        try:
            content = path.read_text(encoding="utf-8")
        except Exception as exc:
            raise DatasetLoadError(
                f"Failed to read dataset file '{path}': {exc}",
                file_path=str(path),
                cause=exc,
            ) from exc

        target_format = (format or "").lower().strip()
        if not target_format:
            target_format = "jsonl" if path.suffix.lower() == ".jsonl" else "json"

        if target_format == "jsonl":
            return self._parse_raw_jsonl(content, source_name=str(path)), {}
        return self._parse_raw_json(content, source_name=str(path))

    def _parse_raw_json(
        self, json_str: str, source_name: str = "json_string"
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Parse raw records and metadata dictionary from JSON string."""
        if not json_str or not json_str.strip():
            raise DatasetLoadError("Empty JSON dataset content.", file_path=source_name)

        try:
            parsed = json.loads(json_str)
        except json.JSONDecodeError as exc:
            raise DatasetLoadError(
                f"Malformed JSON in dataset '{source_name}': {exc}",
                file_path=source_name,
                cause=exc,
            ) from exc

        dataset_meta: Dict[str, Any] = {}
        raw_items: List[Dict[str, Any]] = []

        if isinstance(parsed, list):
            raw_items = parsed
        elif isinstance(parsed, dict):
            raw_items = parsed.get("items", [])
            dataset_meta = {k: v for k, v in parsed.items() if k != "items"}
        else:
            raise DatasetLoadError(
                f"Invalid top-level JSON structure in '{source_name}': expected array or object, got {type(parsed).__name__}.",
                file_path=source_name,
            )

        return raw_items, dataset_meta

    def _parse_raw_jsonl(
        self, jsonl_str: str, source_name: str = "jsonl_string"
    ) -> List[Dict[str, Any]]:
        """Parse raw records from JSON Lines string."""
        if not jsonl_str or not jsonl_str.strip():
            raise DatasetLoadError("Empty JSONL dataset content.", file_path=source_name)

        lines = jsonl_str.splitlines()
        raw_items: List[Dict[str, Any]] = []

        for line_num, raw_line in enumerate(lines, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DatasetLoadError(
                    f"Malformed JSON on line {line_num} in '{source_name}': {exc}",
                    file_path=source_name,
                    cause=exc,
                ) from exc

            if not isinstance(record, dict):
                raise DatasetLoadError(
                    f"Line {line_num} in '{source_name}' must be a JSON object, got {type(record).__name__}.",
                    file_path=source_name,
                )
            raw_items.append(record)

        return raw_items

    def load_from_file(
        self,
        file_path: Union[str, Path],
        format: Optional[str] = None,
        validate: bool = True,
        strict: bool = True,
    ) -> EvaluationDataset:
        """
        Load an evaluation dataset from a JSON or JSONL file on disk.

        Args:
            file_path: Path to the dataset file.
            format: Optional format override: 'json' or 'jsonl'. Defaults to auto-detecting from file extension.
            validate: Whether to run dataset validation.
            strict: Whether to raise DatasetValidationError on validation failure.

        Returns:
            EvaluationDataset instance.

        Raises:
            DatasetLoadError: If file cannot be read or parsed.
            DatasetValidationError: If validation fails and strict=True.
        """
        raw_items, dataset_meta = self.load_raw_from_file(file_path, format=format)

        if validate:
            validation_result = self.validator.validate_raw_records(raw_items, strict=strict)
            if strict and not validation_result.is_valid:
                validation_result.raise_for_status()

        items: List[EvaluationItem] = []
        for index, item_dict in enumerate(raw_items):
            try:
                items.append(EvaluationItem.model_validate(item_dict))
            except Exception as exc:
                if strict:
                    raise DatasetValidationError(
                        f"Failed to instantiate EvaluationItem at index {index}: {exc}"
                    ) from exc

        return EvaluationDataset(
            dataset_name=dataset_meta.get("dataset_name", "RepoLens-Evaluation-Dataset"),
            version=dataset_meta.get("version", "1.0"),
            description=dataset_meta.get("description"),
            metadata=dataset_meta.get("metadata", {}),
            items=items,
        )

    def load_from_json(
        self,
        json_str: str,
        validate: bool = True,
        strict: bool = True,
        source_name: str = "json_string",
    ) -> EvaluationDataset:
        """Parse an EvaluationDataset from a JSON string."""
        raw_items, dataset_meta = self._parse_raw_json(json_str, source_name=source_name)

        if validate:
            validation_result = self.validator.validate_raw_records(raw_items, strict=strict)
            if strict and not validation_result.is_valid:
                validation_result.raise_for_status()

        # Construct EvaluationItem models
        items: List[EvaluationItem] = []
        for index, item_dict in enumerate(raw_items):
            try:
                items.append(EvaluationItem.model_validate(item_dict))
            except Exception as exc:
                if strict:
                    raise DatasetValidationError(
                        f"Failed to instantiate EvaluationItem at index {index}: {exc}"
                    ) from exc

        return EvaluationDataset(
            dataset_name=dataset_meta.get("dataset_name", "RepoLens-Evaluation-Dataset"),
            version=dataset_meta.get("version", "1.0"),
            description=dataset_meta.get("description"),
            metadata=dataset_meta.get("metadata", {}),
            items=items,
        )

    def load_from_jsonl(
        self,
        jsonl_str: str,
        validate: bool = True,
        strict: bool = True,
        source_name: str = "jsonl_string",
    ) -> EvaluationDataset:
        """Parse an EvaluationDataset from a JSON Lines string."""
        raw_items = self._parse_raw_jsonl(jsonl_str, source_name=source_name)

        if validate:
            validation_result = self.validator.validate_raw_records(raw_items, strict=strict)
            if strict and not validation_result.is_valid:
                validation_result.raise_for_status()

        items: List[EvaluationItem] = []
        for index, item_dict in enumerate(raw_items):
            try:
                items.append(EvaluationItem.model_validate(item_dict))
            except Exception as exc:
                if strict:
                    raise DatasetValidationError(
                        f"Failed to instantiate EvaluationItem from JSONL line {index + 1}: {exc}"
                    ) from exc

        return EvaluationDataset(
            dataset_name="RepoLens-Evaluation-Dataset-JSONL",
            version="1.0",
            items=items,
        )

    def save_to_file(
        self,
        dataset: EvaluationDataset,
        file_path: Union[str, Path],
        format: Optional[str] = None,
    ) -> None:
        """Serialize and save an EvaluationDataset to disk as JSON or JSONL."""
        path = Path(file_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)

        target_format = (format or "").lower().strip()
        if not target_format:
            if path.suffix.lower() == ".jsonl":
                target_format = "jsonl"
            else:
                target_format = "json"

        if target_format == "jsonl":
            content = dataset.to_jsonl()
        else:
            content = dataset.to_json(indent=2)

        path.write_text(content, encoding="utf-8")
        logger.info(
            "dataset_saved_to_file",
            file_path=str(path),
            format=target_format,
            item_count=len(dataset),
        )
