"""
app/modules/search/pipeline/model_schema_contract_analysis.py

High-accuracy Model–Schema Contract Analysis for RepoLens FIX_BUG flow.

This module inspects real class/model definitions, schemas/DTOs, and field usages
to verify contracts without relying on word matching, field-name similarity,
or embedding similarity.

Key Principles:
1. Locate and inspect the actual model/class definition.
2. Locate the schema/DTO and all meaningful references to the field.
3. Verify whether the field actually exists on the model.
4. If missing, inspect existing model fields/usages for a possible equivalent field
   using concrete code evidence (mappings, model methods, repository usages).
   Similar names alone are NOT enough.
5. Determine whether the issue is:
   - MODEL_FIELD_MISSING
   - FIELD_MAPPING_MISMATCH
   - WRONG_FIELD_REFERENCE
   - AMBIGUOUS
   - INSUFFICIENT_EVIDENCE
6. Set field_confirmed_absent=True ONLY when the actual model definition has been
   found and inspected.
7. Never automatically suggest adding a database/model field just because it is missing.
8. Pass only verified evidence to the LLM for fix reasoning.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any

from app.core.enums import IntentType
from app.core.logging import get_logger
from app.modules.search.domain.search_domain import RetrievedChunk, SearchContext

logger = get_logger(__name__)


class ContractIssueType(str, Enum):
    MODEL_FIELD_MISSING = "MODEL_FIELD_MISSING"
    FIELD_MAPPING_MISMATCH = "FIELD_MAPPING_MISMATCH"
    WRONG_FIELD_REFERENCE = "WRONG_FIELD_REFERENCE"
    AMBIGUOUS = "AMBIGUOUS"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass
class ModelField:
    """Represents a verified field on a model definition."""

    name: str
    field_type: str | None = None
    line_number: int | None = None
    is_property: bool = False
    is_method: bool = False
    is_column: bool = False
    docstring: str | None = None


@dataclass
class ModelDefinition:
    """Represents a verified model or class definition inspected from code."""

    class_name: str
    file_path: str
    fields: dict[str, ModelField] = field(default_factory=dict)
    raw_code: str = ""
    start_line: int | None = None
    end_line: int | None = None
    methods: list[str] = field(default_factory=list)
    docstring: str | None = None


@dataclass
class SchemaReference:
    """Represents a schema/DTO or caller reference to a field."""

    file_path: str
    schema_or_caller_name: str | None
    field_name: str
    line_number: int | None = None
    reference_type: str = "field_access"  # "schema_field", "field_access", "mapping"
    mapping_target: str | None = None
    code_snippet: str = ""


@dataclass
class ContractAnalysisResult:
    """Result of Model-Schema Contract Analysis."""

    is_applicable: bool
    issue_type: ContractIssueType
    target_class: str | None
    suspicious_field: str | None
    model_definition: ModelDefinition | None
    field_confirmed_absent: bool
    schema_references: list[SchemaReference] = field(default_factory=list)
    equivalent_field: str | None = None
    equivalent_field_evidence: str | None = None
    evidence_summary: str = ""
    candidate_models: list[dict[str, Any]] = field(default_factory=list)
    verified_facts: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_applicable": self.is_applicable,
            "issue_type": self.issue_type.value,
            "target_class": self.target_class,
            "suspicious_field": self.suspicious_field,
            "model_file": self.model_definition.file_path if self.model_definition else None,
            "model_fields": list(self.model_definition.fields.keys()) if self.model_definition else [],
            "field_confirmed_absent": self.field_confirmed_absent,
            "equivalent_field": self.equivalent_field,
            "equivalent_field_evidence": self.equivalent_field_evidence,
            "evidence_summary": self.evidence_summary,
            "candidate_models": self.candidate_models,
            "verified_facts": self.verified_facts,
            "schema_references": [
                {
                    "file_path": ref.file_path,
                    "caller": ref.schema_or_caller_name,
                    "field": ref.field_name,
                    "type": ref.reference_type,
                    "mapping_target": ref.mapping_target,
                }
                for ref in self.schema_references
            ],
        }


# ---------------------------------------------------------------------------
# AST & Structural Model Extractors
# ---------------------------------------------------------------------------

def _parse_python_class_ast(
    code: str,
    file_path: str,
) -> list[ModelDefinition]:
    """Parse Python code using AST to find all class definitions and fields."""
    models: list[ModelDefinition] = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        # Fallback to regex-based extraction if code snippet is partial
        return _parse_python_class_regex(code, file_path)

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        fields_dict: dict[str, ModelField] = {}
        methods_list: list[str] = []

        # 1. Class-level statements
        for item in node.body:
            # Annotated assignments: x: str, x: int = 1
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                field_name = item.target.id
                fields_dict[field_name] = ModelField(
                    name=field_name,
                    line_number=getattr(item, "lineno", None),
                )
            # Normal assignments: x = Column(...), x = None
            elif isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        field_name = target.id
                        fields_dict[field_name] = ModelField(
                            name=field_name,
                            line_number=getattr(item, "lineno", None),
                            is_column=True,
                        )
            # Method definitions and @property
            elif isinstance(item, ast.FunctionDef):
                methods_list.append(item.name)
                is_prop = any(
                    isinstance(dec, ast.Name) and dec.id == "property"
                    or (isinstance(dec, ast.Attribute) and dec.attr == "getter")
                    for dec in item.decorator_list
                )
                if is_prop:
                    fields_dict[item.name] = ModelField(
                        name=item.name,
                        line_number=getattr(item, "lineno", None),
                        is_property=True,
                    )
                # Inspect __init__ for self.field = ...
                if item.name == "__init__":
                    for stmt in ast.walk(item):
                        if (
                            isinstance(stmt, ast.Assign)
                            and len(stmt.targets) == 1
                            and isinstance(stmt.targets[0], ast.Attribute)
                            and isinstance(stmt.targets[0].value, ast.Name)
                            and stmt.targets[0].value.id == "self"
                        ):
                            attr_name = stmt.targets[0].attr
                            if attr_name not in fields_dict:
                                fields_dict[attr_name] = ModelField(
                                    name=attr_name,
                                    line_number=getattr(stmt, "lineno", None),
                                )

        models.append(
            ModelDefinition(
                class_name=node.name,
                file_path=file_path,
                fields=fields_dict,
                raw_code=code,
                start_line=getattr(node, "lineno", None),
                end_line=getattr(node, "end_lineno", None),
                methods=methods_list,
                docstring=ast.get_docstring(node),
            )
        )

    return models


def _parse_python_class_regex(
    code: str,
    file_path: str,
) -> list[ModelDefinition]:
    """Regex fallback for partial Python class snippets."""
    models: list[ModelDefinition] = []
    class_pattern = re.compile(
        r"class\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s*\([^)]*\))?\s*:",
        re.MULTILINE,
    )

    for match in class_pattern.finditer(code):
        class_name = match.group(1)
        fields_dict: dict[str, ModelField] = {}
        methods_list: list[str] = []

        body = code[match.end():]
        # Match indented class lines
        for line in body.splitlines():
            if line and not line.startswith((" ", "\t", "#")):
                break  # Dedented - end of class

            # Match field annotations or assignments: `date = Column(...)` or `date: datetime`
            field_match = re.match(
                r"^\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?::\s*[^=\n]+)?(?:\s*=\s*.+)?$",
                line,
            )
            if field_match:
                fname = field_match.group(1)
                if fname not in ("def", "class", "return", "pass", "import", "from"):
                    fields_dict[fname] = ModelField(name=fname)

            # Match self.x = ...
            self_match = re.search(r"self\.([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
            if self_match:
                fname = self_match.group(1)
                fields_dict[fname] = ModelField(name=fname)

            # Match def method
            def_match = re.search(r"def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", line)
            if def_match:
                mname = def_match.group(1)
                methods_list.append(mname)

        models.append(
            ModelDefinition(
                class_name=class_name,
                file_path=file_path,
                fields=fields_dict,
                raw_code=code,
                methods=methods_list,
            )
        )

    return models


def _parse_ts_js_class_or_interface(
    code: str,
    file_path: str,
) -> list[ModelDefinition]:
    """Parse TypeScript / JavaScript classes, interfaces, and type declarations."""
    models: list[ModelDefinition] = []

    pattern = re.compile(
        r"(?:export\s+)?(?:interface|class|type)\s+([A-Za-z_][A-Za-z0-9_]*)"
        r"(?:\s+extends\s+[^{]+|\s+implements\s+[^{]+|\s*=\s*)?\s*\{([^}]*)\}",
        re.MULTILINE | re.DOTALL,
    )

    for match in pattern.finditer(code):
        class_name = match.group(1)
        body = match.group(2)
        fields_dict: dict[str, ModelField] = {}
        methods_list: list[str] = []

        for line in body.splitlines():
            line_str = line.strip()
            if not line_str or line_str.startswith("//") or line_str.startswith("/*"):
                continue

            # Property: `name: string;`, `phone?: string;`, `id: number,`
            prop_match = re.match(
                r"^([A-Za-z_][A-Za-z0-9_]*)\s*\??\s*:\s*([^;,]+)",
                line_str,
            )
            if prop_match:
                fname = prop_match.group(1)
                ftype = prop_match.group(2).strip()
                fields_dict[fname] = ModelField(name=fname, field_type=ftype)
                continue

            # Class property assignment: `name = 'test';`
            assign_match = re.match(
                r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*",
                line_str,
            )
            if assign_match:
                fname = assign_match.group(1)
                fields_dict[fname] = ModelField(name=fname)
                continue

            # Method or getter: `get fullName()`, `login()`
            getter_match = re.match(
                r"^(?:get\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\([^)]*\)",
                line_str,
            )
            if getter_match:
                mname = getter_match.group(1)
                methods_list.append(mname)
                if line_str.startswith("get "):
                    fields_dict[mname] = ModelField(name=mname, is_property=True)

        # Check this.x = ... inside class body
        this_matches = re.finditer(r"this\.([A-Za-z_][A-Za-z0-9_]*)\s*=", code)
        for tm in this_matches:
            fname = tm.group(1)
            fields_dict[fname] = ModelField(name=fname)

        models.append(
            ModelDefinition(
                class_name=class_name,
                file_path=file_path,
                fields=fields_dict,
                raw_code=code,
                methods=methods_list,
            )
        )

    return models


def inspect_model_definitions(
    chunks: list[RetrievedChunk],
    target_class: str | None = None,
) -> list[ModelDefinition]:
    """Inspect retrieved chunks to extract concrete model/class definitions."""
    definitions: list[ModelDefinition] = []

    for chunk in chunks:
        file_path = chunk.file_path or ""
        content = chunk.content or ""
        fp_lower = file_path.lower()

        # Parse Python files or python-like snippets
        if fp_lower.endswith((".py", ".pyi")) or "class " in content or "def " in content:
            found = _parse_python_class_ast(content, file_path)
            for m in found:
                if not target_class or m.class_name.lower() == target_class.lower():
                    definitions.append(m)

        # Parse TS/JS files
        if fp_lower.endswith((".ts", ".tsx", ".js", ".jsx")) or "interface " in content:
            found = _parse_ts_js_class_or_interface(content, file_path)
            for m in found:
                if not target_class or m.class_name.lower() == target_class.lower():
                    definitions.append(m)

    return definitions


# ---------------------------------------------------------------------------
# Schema, DTO & Reference Extractor
# ---------------------------------------------------------------------------

def inspect_schema_references(
    chunks: list[RetrievedChunk],
    target_class: str | None = None,
    suspicious_field: str | None = None,
) -> list[SchemaReference]:
    """Locate schema/DTO definitions, serializer mappings, and caller field references."""
    references: list[SchemaReference] = []

    for chunk in chunks:
        file_path = chunk.file_path or ""
        content = chunk.content or ""

        # 1. Look for Schema/DTO/Serializer attribute mappings
        # e.g., `phone_number = fields.Str(attribute="phone")`
        # e.g., `Field(alias="phone")`
        # e.g., `date = fields.DateTime(...)`
        lines = content.splitlines()
        for idx, line in enumerate(lines, 1):
            line_str = line.strip()

            # Attribute mapping in Marshmallow / DRF / Pydantic
            map_match = re.search(
                r'([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:fields\.[A-Za-z]+|Field)\([^)]*(?:attribute|alias|source)=["\']([A-Za-z0-9_]+)["\']',
                line_str,
            )
            if map_match:
                s_field = map_match.group(1)
                m_target = map_match.group(2)
                references.append(
                    SchemaReference(
                        file_path=file_path,
                        schema_or_caller_name=chunk.metadata.get("class_name") or chunk.metadata.get("function_name"),
                        field_name=s_field,
                        line_number=idx,
                        reference_type="mapping",
                        mapping_target=m_target,
                        code_snippet=line_str,
                    )
                )

            # Direct field access on an instance: `appointment.date`, `lead.phone_number`, `user.full_name`
            if suspicious_field:
                access_pattern = re.compile(
                    rf"\b([A-Za-z_][A-Za-z0-9_]*)\.{re.escape(suspicious_field)}\b"
                )
                for amatch in access_pattern.finditer(line_str):
                    var_name = amatch.group(1)
                    references.append(
                        SchemaReference(
                            file_path=file_path,
                            schema_or_caller_name=chunk.metadata.get("function_name") or var_name,
                            field_name=suspicious_field,
                            line_number=idx,
                            reference_type="field_access",
                            code_snippet=line_str,
                        )
                    )

    return references


# ---------------------------------------------------------------------------
# Query & Code Signal Extraction
# ---------------------------------------------------------------------------

def extract_suspicious_field_and_class(
    query: str,
    chunks: list[RetrievedChunk],
) -> tuple[str | None, str | None]:
    """
    Extract the candidate entity/class name and suspicious field name
    from the bug query and retrieved code context.
    """
    target_class: str | None = None
    suspicious_field: str | None = None

    # Common bug patterns:
    # "AttributeError: 'Appointment' object has no attribute 'date'"
    # "'User' object has no attribute 'full_name'"
    attr_err_match = re.search(
        r"['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?\s+object has no attribute\s+['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?",
        query,
        re.IGNORECASE,
    )
    if attr_err_match:
        return attr_err_match.group(1), attr_err_match.group(2)

    # "Missing field 'date' on model 'Appointment'"
    # "Missing 'phone_number' in User schema"
    missing_match = re.search(
        r"missing\s+(?:field\s+)?['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?\s+(?:in|on|from)\s+(?:model\s+|class\s+|schema\s+)?['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?",
        query,
        re.IGNORECASE,
    )
    if missing_match:
        return missing_match.group(2), missing_match.group(1)

    # "Appointment model missing date field"
    # "User schema missing phone_number"
    model_missing_match = re.search(
        r"['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?\s+(?:model|schema|dto|class|entity)?\s*missing\s+(?:field\s+)?['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?",
        query,
        re.IGNORECASE,
    )
    if model_missing_match:
        return model_missing_match.group(1), model_missing_match.group(2)

    # "Fix appointment date selection error" -> Entity: Appointment, Field: date
    # Check words against known class and field patterns in chunks
    all_content = "\n".join(c.content for c in chunks if c.content)
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", query)

    # Detect known class names in chunks
    class_names = set(re.findall(r"class\s+([A-Za-z_][A-Za-z0-9_]*)", all_content))
    interface_names = set(re.findall(r"interface\s+([A-Za-z_][A-Za-z0-9_]*)", all_content))
    known_entities = class_names | interface_names

    for token in tokens:
        for ent in known_entities:
            if token.lower() == ent.lower():
                target_class = ent
                break
        if target_class:
            break

    # Look for candidate field tokens
    generic_stopwords = {
        "fix", "the", "a", "an", "in", "on", "at", "to", "for", "with",
        "error", "bug", "issue", "fail", "failure", "broken", "model",
        "schema", "dto", "class", "field", "property", "attribute",
    }
    candidate_field_tokens = [
        t for t in tokens
        if t.lower() not in generic_stopwords and (not target_class or t.lower() != target_class.lower())
    ]

    if candidate_field_tokens:
        suspicious_field = candidate_field_tokens[0]

    return target_class, suspicious_field


# ---------------------------------------------------------------------------
# Equivalent Field Verification (Strictly NO word similarity / embeddings)
# ---------------------------------------------------------------------------

def find_equivalent_field(
    model: ModelDefinition,
    schema_refs: list[SchemaReference],
    chunks: list[RetrievedChunk],
    suspicious_field: str,
) -> tuple[str | None, str | None]:
    """
    Inspect model methods, schema mappings, and repository field usages
    to verify if an equivalent field exists on the model.

    CRITICAL RULE:
    Similar names alone are NOT enough.
    Must be backed by real code evidence:
    1. Explicit schema/DTO attribute mapping (e.g. attribute="phone" -> model has phone)
    2. Model method / property / composition (e.g. get_full_name() or property computing it)
    3. Direct usages across functions/queries in the repository operating on the same model.
    """
    # 1. Schema mapping evidence
    for ref in schema_refs:
        if ref.field_name.lower() == suspicious_field.lower() and ref.mapping_target:
            if ref.mapping_target in model.fields:
                evidence = (
                    f"Schema mapping in {ref.file_path} maps '{ref.field_name}' "
                    f"to model field '{ref.mapping_target}'."
                )
                return ref.mapping_target, evidence

    # 2. Model method or property evidence
    # e.g., model has a method `get_<field>` or property `<field>`
    for method in model.methods:
        if method.lower() in (f"get_{suspicious_field.lower()}", f"find_{suspicious_field.lower()}"):
            evidence = (
                f"Model {model.class_name} in {model.file_path} provides method "
                f"'{method}()' to access the required data."
            )
            return method, evidence

    # 3. Repository field usage evidence
    # Look for how callers/services in retrieved chunks use instances of this model
    # E.g. in `appointment_service.py`, `appointment.start_time` is used where `date` was queried
    model_var_names = {
        model.class_name.lower(),
        model.class_name.lower()[:4],
        "obj",
        "instance",
        "entity",
    }
    for chunk in chunks:
        content = chunk.content or ""
        # Find property accesses like `appointment.scheduled_time` or `user.email`
        for mfield in model.fields.keys():
            if mfield.lower() == suspicious_field.lower():
                continue
            for var in model_var_names:
                pattern = rf"\b{re.escape(var)}\.{re.escape(mfield)}\b"
                if re.search(pattern, content):
                    # Verified that other usages in repo access this model field
                    # Check if there is an explicit correlation in the chunk
                    if suspicious_field.lower() in content.lower() and chunk.file_path != model.file_path:
                        evidence = (
                            f"Usage in {chunk.file_path} accesses model field "
                            f"'{mfield}' on {model.class_name} instance."
                        )
                        return mfield, evidence

    return None, None


# ---------------------------------------------------------------------------
# Contract Analyzer
# ---------------------------------------------------------------------------

class ModelSchemaContractAnalyzer:
    """Core analyzer for Model–Schema Contract Analysis."""

    def analyze(self, context: SearchContext) -> ContractAnalysisResult:
        """
        Execute Model-Schema Contract Analysis on the search context.
        """
        if context.intent != IntentType.FIX_BUG:
            return ContractAnalysisResult(
                is_applicable=False,
                issue_type=ContractIssueType.INSUFFICIENT_EVIDENCE,
                target_class=None,
                suspicious_field=None,
                model_definition=None,
                field_confirmed_absent=False,
            )

        chunks = context.retrieved_chunks or []
        query = context.query or ""

        # Step 1: Identify suspicious field and object/class
        target_class, suspicious_field = extract_suspicious_field_and_class(query, chunks)

        if not target_class or not suspicious_field:
            return ContractAnalysisResult(
                is_applicable=False,
                issue_type=ContractIssueType.INSUFFICIENT_EVIDENCE,
                target_class=target_class,
                suspicious_field=suspicious_field,
                model_definition=None,
                field_confirmed_absent=False,
                evidence_summary="Could not identify target class and suspicious field from query and code.",
            )

        # Step 2: Locate and inspect actual model/class definition
        all_models = inspect_model_definitions(chunks, target_class=target_class)

        # Ambiguity check: Multiple conflicting candidate model definitions across files
        if len(all_models) > 1:
            # Check if models are from distinct files with different definitions
            distinct_files = {m.file_path for m in all_models}
            if len(distinct_files) > 1:
                candidate_list = [
                    {
                        "class_name": m.class_name,
                        "file_path": m.file_path,
                        "fields": list(m.fields.keys()),
                    }
                    for m in all_models
                ]
                return ContractAnalysisResult(
                    is_applicable=True,
                    issue_type=ContractIssueType.AMBIGUOUS,
                    target_class=target_class,
                    suspicious_field=suspicious_field,
                    model_definition=None,
                    field_confirmed_absent=False,  # CRITICAL: Not confirmed absent when ambiguous
                    candidate_models=candidate_list,
                    evidence_summary=(
                        f"Multiple candidate model definitions for '{target_class}' "
                        f"were found across files: {', '.join(distinct_files)}. "
                        "Target model is ambiguous."
                    ),
                )

        # Insufficient evidence check: Model definition not found
        if not all_models:
            return ContractAnalysisResult(
                is_applicable=True,
                issue_type=ContractIssueType.INSUFFICIENT_EVIDENCE,
                target_class=target_class,
                suspicious_field=suspicious_field,
                model_definition=None,
                field_confirmed_absent=False,  # CRITICAL: Must be False when model not inspected
                evidence_summary=(
                    f"Model/class definition for '{target_class}' was not found in retrieved chunks. "
                    "Cannot verify field existence."
                ),
            )

        model = all_models[0]

        # Step 3: Locate schema/DTO and references
        schema_refs = inspect_schema_references(
            chunks,
            target_class=target_class,
            suspicious_field=suspicious_field,
        )

        # Step 4: Verify whether field exists on model
        field_exists = suspicious_field in model.fields

        if field_exists:
            # Field is present on the model definition
            return ContractAnalysisResult(
                is_applicable=True,
                issue_type=ContractIssueType.INSUFFICIENT_EVIDENCE,
                target_class=target_class,
                suspicious_field=suspicious_field,
                model_definition=model,
                field_confirmed_absent=False,
                schema_references=schema_refs,
                evidence_summary=(
                    f"Field '{suspicious_field}' exists on model '{model.class_name}' "
                    f"in {model.file_path}."
                ),
                verified_facts={
                    "model_class": model.class_name,
                    "model_file": model.file_path,
                    "field_present": True,
                },
            )

        # Step 5 & 7: Field is absent on the inspected model
        # Set field_confirmed_absent = True only because model was found and inspected
        field_confirmed_absent = True

        # Inspect for equivalent field
        equiv_field, equiv_evidence = find_equivalent_field(
            model=model,
            schema_refs=schema_refs,
            chunks=chunks,
            suspicious_field=suspicious_field,
        )

        # Step 6: Determine issue category
        if equiv_field:
            # Check if reference is in a schema or a caller
            has_schema_mapping = any(ref.reference_type == "mapping" for ref in schema_refs)
            if has_schema_mapping:
                issue_type = ContractIssueType.FIELD_MAPPING_MISMATCH
                summary = (
                    f"Field mapping mismatch: Schema references '{suspicious_field}', "
                    f"while model '{model.class_name}' in {model.file_path} defines '{equiv_field}'. "
                    f"{equiv_evidence}"
                )
            else:
                issue_type = ContractIssueType.WRONG_FIELD_REFERENCE
                summary = (
                    f"Wrong field reference: Caller references '{suspicious_field}', "
                    f"while model '{model.class_name}' in {model.file_path} defines '{equiv_field}'. "
                    f"{equiv_evidence}"
                )
        else:
            issue_type = ContractIssueType.MODEL_FIELD_MISSING
            summary = (
                f"Model field missing: Field '{suspicious_field}' does not exist on model "
                f"'{model.class_name}' ({model.file_path}). "
                f"Existing model fields: {', '.join(sorted(model.fields.keys()))}. "
                "No equivalent field was verified in model or usages."
            )

        verified_facts = {
            "model_class": model.class_name,
            "model_file": model.file_path,
            "model_fields": sorted(list(model.fields.keys())),
            "suspicious_field": suspicious_field,
            "field_confirmed_absent": field_confirmed_absent,
            "equivalent_field": equiv_field,
            "equivalent_field_evidence": equiv_evidence,
            "issue_type": issue_type.value,
        }

        return ContractAnalysisResult(
            is_applicable=True,
            issue_type=issue_type,
            target_class=target_class,
            suspicious_field=suspicious_field,
            model_definition=model,
            field_confirmed_absent=field_confirmed_absent,
            schema_references=schema_refs,
            equivalent_field=equiv_field,
            equivalent_field_evidence=equiv_evidence,
            evidence_summary=summary,
            verified_facts=verified_facts,
        )


def format_contract_evidence_for_llm(result: ContractAnalysisResult) -> str:
    """Format verified contract facts for inclusion in LLM prompt."""
    if not result.is_applicable:
        return ""

    lines = [
        "--- MODEL-SCHEMA CONTRACT ANALYSIS (VERIFIED CODE FACTS) ---",
        f"Issue Type: {result.issue_type.value}",
        f"Target Class / Entity: {result.target_class or 'Unknown'}",
        f"Suspicious Field: {result.suspicious_field or 'Unknown'}",
        f"Field Confirmed Absent: {'TRUE' if result.field_confirmed_absent else 'FALSE'}",
    ]

    if result.model_definition:
        lines.append(f"Model File: {result.model_definition.file_path}")
        fields_str = ", ".join(sorted(result.model_definition.fields.keys()))
        lines.append(f"Inspected Model Fields: [{fields_str}]")

    if result.equivalent_field:
        lines.append(f"Verified Equivalent Field: {result.equivalent_field}")
        if result.equivalent_field_evidence:
            lines.append(f"Equivalence Evidence: {result.equivalent_field_evidence}")

    lines.append(f"Evidence Summary: {result.evidence_summary}")
    lines.append(
        "RULE: Base fix reasoning strictly on these verified facts. "
        "Do NOT invent unverified model fields, database columns, or files."
    )
    lines.append("-------------------------------------------------------------")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pipeline Stage
# ---------------------------------------------------------------------------

class ModelSchemaContractAnalysisStage:
    """
    Pipeline stage for Model-Schema Contract Analysis in FIX_BUG flow.
    """

    def __init__(self) -> None:
        self.analyzer = ModelSchemaContractAnalyzer()

    async def execute(self, context: SearchContext) -> None:
        """Execute contract analysis and record findings on SearchContext."""
        if context.early_exit or context.intent != IntentType.FIX_BUG:
            return

        result = self.analyzer.analyze(context)
        context.contract_analysis = result.to_dict()

        logger.info(
            "model_schema_contract_analysis_executed",
            is_applicable=result.is_applicable,
            issue_type=result.issue_type.value,
            target_class=result.target_class,
            suspicious_field=result.suspicious_field,
            field_confirmed_absent=result.field_confirmed_absent,
            equivalent_field=result.equivalent_field,
        )

        # If ambiguous models found, mark ambiguity on context
        if result.issue_type == ContractIssueType.AMBIGUOUS:
            context.ambiguous = True
            context.is_ambiguous = True
            context.symbol_conflict = True
            context.ambiguous_candidates = result.candidate_models
            context.early_exit = "EARLY_EXIT_C"
            context.early_exit_message = result.evidence_summary
