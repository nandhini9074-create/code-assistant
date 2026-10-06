"""
tests/unit/search/test_model_schema_contract_analysis.py

Unit tests for Model-Schema Contract Analysis in RepoLens FIX_BUG flow.
Tests verify:
1. Missing fields (MODEL_FIELD_MISSING)
2. Equivalent fields (FIELD_MAPPING_MISMATCH and WRONG_FIELD_REFERENCE)
3. Ambiguous models (AMBIGUOUS)
4. Insufficient evidence (INSUFFICIENT_EVIDENCE)
5. Strict field_confirmed_absent flag verification
6. Non-reliance on simple string similarity
7. Pipeline integration across all stages
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest

from app.core.enums import IntentType
from app.modules.code_analysis.analyzers.fix_bug_analyzer import FixBugAnalyzer
from app.modules.search.domain.search_domain import RetrievedChunk, SearchContext
from app.modules.search.pipeline.code_identification import CodeIdentificationStage
from app.modules.search.pipeline.context_builder import ContextBuilderStage
from app.modules.search.pipeline.model_schema_contract_analysis import (
    ContractIssueType,
    ModelSchemaContractAnalysisStage,
    ModelSchemaContractAnalyzer,
    format_contract_evidence_for_llm,
)
from app.modules.search.pipeline.action_analysis import ActionAnalysisStage
from app.modules.search.pipeline.final_triage import FinalTriageStage
from app.modules.search.pipeline.suggestion_patch import SuggestionPatchStage


def _chunk(
    chunk_hash: str,
    file_path: str,
    content: str,
    symbol: str | None = None,
    score: float = 0.85,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_hash=chunk_hash,
        file_path=file_path,
        content=content,
        score=score,
        metadata={
            "symbol": symbol,
            "function_name": symbol,
            "class_name": symbol,
            "start_line": 1,
            "end_line": len(content.splitlines()),
        },
    )


def test_missing_field_confirmed_absent_when_model_inspected():
    """
    When model definition is located and inspected, and field is not present
    with no equivalent field, determine MODEL_FIELD_MISSING and set
    field_confirmed_absent=True.
    """
    model_code = """
class Appointment:
    id: int
    title: str
    doctor_id: int
    patient_id: int
"""
    caller_code = """
def process_appointment(app: Appointment):
    return app.location
"""
    model_chunk = _chunk("model_1", "app/models/appointment.py", model_code, "Appointment")
    caller_chunk = _chunk("caller_1", "app/services/appointment_service.py", caller_code, "process_appointment")

    context = SearchContext(
        query="AttributeError: 'Appointment' object has no attribute 'location'",
        intent=IntentType.FIX_BUG,
        retrieved_chunks=[model_chunk, caller_chunk],
    )

    analyzer = ModelSchemaContractAnalyzer()
    result = analyzer.analyze(context)

    assert result.is_applicable is True
    assert result.issue_type == ContractIssueType.MODEL_FIELD_MISSING
    assert result.target_class == "Appointment"
    assert result.suspicious_field == "location"
    assert result.field_confirmed_absent is True
    assert result.equivalent_field is None
    assert result.model_definition is not None
    assert "location" not in result.model_definition.fields
    assert "doctor_id" in result.model_definition.fields


def test_equivalent_field_via_schema_mapping():
    """
    When schema maps phone_number to phone attribute, but model has phone,
    determine FIELD_MAPPING_MISMATCH with verified evidence.
    """
    model_code = """
class Lead:
    id: int
    name: str
    phone: str
    email: str
"""
    schema_code = """
from marshmallow import Schema, fields

class LeadSchema(Schema):
    id = fields.Int()
    name = fields.Str()
    phone_number = fields.Str(attribute="phone")
"""
    model_chunk = _chunk("model_1", "app/models/lead.py", model_code, "Lead")
    schema_chunk = _chunk("schema_1", "app/schemas/lead_schema.py", schema_code, "LeadSchema")

    context = SearchContext(
        query="Fix missing phone_number in Lead model",
        intent=IntentType.FIX_BUG,
        retrieved_chunks=[model_chunk, schema_chunk],
    )

    analyzer = ModelSchemaContractAnalyzer()
    result = analyzer.analyze(context)

    assert result.is_applicable is True
    assert result.issue_type == ContractIssueType.FIELD_MAPPING_MISMATCH
    assert result.target_class == "Lead"
    assert result.suspicious_field == "phone_number"
    assert result.field_confirmed_absent is True
    assert result.equivalent_field == "phone"
    assert "maps 'phone_number' to model field 'phone'" in result.equivalent_field_evidence


def test_equivalent_field_via_caller_usages():
    """
    When caller queries date but model defines scheduled_time and other service
    functions use appointment.scheduled_time, determine WRONG_FIELD_REFERENCE.
    """
    model_code = """
class Appointment:
    id: int
    patient_id: int
    scheduled_time: str
"""
    service_code = """
def get_appointment_date(appointment: Appointment):
    # Buggy access
    return appointment.date

def list_appointments(appointment: Appointment):
    # Established usage in repo
    return appointment.scheduled_time
"""
    model_chunk = _chunk("model_1", "app/models/appointment.py", model_code, "Appointment")
    service_chunk = _chunk("service_1", "app/services/appointment_service.py", service_code, "get_appointment_date")

    context = SearchContext(
        query="Fix appointment date error in Appointment",
        intent=IntentType.FIX_BUG,
        retrieved_chunks=[model_chunk, service_chunk],
    )

    analyzer = ModelSchemaContractAnalyzer()
    result = analyzer.analyze(context)

    assert result.is_applicable is True
    assert result.issue_type == ContractIssueType.WRONG_FIELD_REFERENCE
    assert result.target_class == "Appointment"
    assert result.suspicious_field == "date"
    assert result.field_confirmed_absent is True
    assert result.equivalent_field == "scheduled_time"


def test_ambiguous_models_across_distinct_files():
    """
    When multiple distinct model definitions for the same class exist in different files,
    mark AMBIGUOUS and do NOT confirm field absent.
    """
    model_v1 = """
class User:
    id: int
    username: str
"""
    model_v2 = """
class User:
    id: int
    username: str
    email_address: str
"""
    chunk1 = _chunk("v1", "app/models/v1/user.py", model_v1, "User")
    chunk2 = _chunk("v2", "app/models/v2/user.py", model_v2, "User")

    context = SearchContext(
        query="User model missing email_address",
        intent=IntentType.FIX_BUG,
        retrieved_chunks=[chunk1, chunk2],
    )

    analyzer = ModelSchemaContractAnalyzer()
    result = analyzer.analyze(context)

    assert result.is_applicable is True
    assert result.issue_type == ContractIssueType.AMBIGUOUS
    assert result.field_confirmed_absent is False  # Must be False when ambiguous!
    assert len(result.candidate_models) == 2


def test_insufficient_evidence_when_model_not_found():
    """
    When model definition is NOT in retrieved chunks, determine INSUFFICIENT_EVIDENCE
    and do NOT confirm field absent.
    """
    service_code = """
def calculate_order(order):
    return order.total_amount
"""
    chunk = _chunk("srv", "app/services/order_service.py", service_code, "calculate_order")

    context = SearchContext(
        query="Order model missing total_amount",
        intent=IntentType.FIX_BUG,
        retrieved_chunks=[chunk],
    )

    analyzer = ModelSchemaContractAnalyzer()
    result = analyzer.analyze(context)

    assert result.is_applicable is True
    assert result.issue_type == ContractIssueType.INSUFFICIENT_EVIDENCE
    assert result.field_confirmed_absent is False  # Must be False when model not found!
    assert result.model_definition is None


@pytest.mark.asyncio
async def test_code_identification_marks_ambiguity_early():
    """
    CodeIdentificationStage respects ambiguous contract analysis and exits early.
    """
    model_v1 = "class Customer:\n    id: int\n"
    model_v2 = "class Customer:\n    name: str\n"
    chunk1 = _chunk("c1", "app/models/crm/customer.py", model_v1, "Customer")
    chunk2 = _chunk("c2", "app/models/billing/customer.py", model_v2, "Customer")

    context = SearchContext(
        query="Customer model missing address",
        intent=IntentType.FIX_BUG,
        retrieved_chunks=[chunk1, chunk2],
    )

    stage = CodeIdentificationStage(llm_service=None)
    await stage.execute(context)

    assert context.ambiguous is True
    assert context.early_exit == "EARLY_EXIT_C"
    assert "ambiguous" in context.early_exit_message.lower()


@pytest.mark.asyncio
async def test_fix_bug_analyzer_prevents_unsafe_database_model_modification():
    """
    When contract analysis determines FIELD_MAPPING_MISMATCH, FixBugAnalyzer
    prevents the LLM from modifying the database model file.
    """
    model_code = "class Lead:\n    id: int\n    phone: str\n"
    schema_code = 'class LeadSchema:\n    phone_number = fields.Str(attribute="phone")\n'

    model_chunk = _chunk("m1", "app/models/lead.py", model_code, "Lead")
    schema_chunk = _chunk("s1", "app/schemas/lead.py", schema_code, "LeadSchema")

    # LLM incorrectly attempts to modify the model file
    hallucinated_llm_response = {
        "analysis_status": "OK",
        "evidence_summary": "Lead model in app/models/lead.py is missing phone_number.",
        "current_behavior": "Lead does not have phone_number column.",
        "problematic_code": "class Lead:",
        "likely_cause": "Database model missing column.",
        "proposed_fix": "Add phone_number to database model.",
        "proposed_change": "Add phone_number field to Lead class.",
        "code_change": {
            "file_path": "app/models/lead.py",
            "symbol": "Lead",
            "start_line": 1,
            "end_line": 3,
            "old_code": "class Lead:\n    id: int\n    phone: str",
            "new_code": "class Lead:\n    id: int\n    phone: str\n    phone_number: str",
        },
        "suggested_code": "class Lead:\n    id: int\n    phone: str\n    phone_number: str",
    }

    llm_service = SimpleNamespace(
        provider=SimpleNamespace(complete_json=AsyncMock(return_value=hallucinated_llm_response))
    )

    context = SearchContext(
        query="Fix missing phone_number on Lead model",
        intent=IntentType.FIX_BUG,
        retrieved_chunks=[model_chunk, schema_chunk],
    )

    analyzer = FixBugAnalyzer(llm_service)
    result = await analyzer.analyze(context)

    # Unsafe DB model modification was prevented
    assert result.analysis["code_change"] is None
    assert "instead of modifying the database model" in result.analysis["proposed_fix"]


@pytest.mark.asyncio
async def test_full_pipeline_flow_action_and_triage_integration():
    """
    Test integration through ActionAnalysisStage and FinalTriageStage
    with verified contract analysis.
    """
    model_code = "class Lead:\n    id: int\n    phone: str\n"
    schema_code = 'class LeadSchema:\n    phone_number = fields.Str(attribute="phone")\n'

    model_chunk = _chunk("m1", "app/models/lead.py", model_code, "Lead")
    schema_chunk = _chunk("s1", "app/schemas/lead.py", schema_code, "LeadSchema")

    context = SearchContext(
        query="Fix missing phone_number on Lead schema",
        intent=IntentType.FIX_BUG,
        retrieved_chunks=[model_chunk, schema_chunk],
        primary_chunk=schema_chunk,
        analysis_result={
            "analysis_status": "OK",
            "evidence_summary": "LeadSchema in app/schemas/lead.py maps phone_number to phone.",
            "current_behavior": "Schema mapping issue.",
            "problematic_code": 'phone_number = fields.Str(attribute="phone")',
            "likely_cause": "Field mapping mismatch.",
            "proposed_fix": "Use verified phone attribute.",
            "proposed_change": "Update schema mapping.",
            "code_change": None,
            "suggested_code": "",
        },
        validated=True,
        validation_status="passed",
    )

    # Run contract analysis
    contract_stage = ModelSchemaContractAnalysisStage()
    await contract_stage.execute(context)

    # Run ActionAnalysisStage
    action_stage = ActionAnalysisStage()
    await action_stage.execute(context)

    assert context.action_analysis is not None
    assert context.action_analysis["action_type"] == "SCHEMA_MAPPING_FIX"

    # Run FinalTriageStage
    triage_stage = FinalTriageStage()
    await triage_stage.execute(context)

    assert context.triage_result is not None
    assert context.triage_result["issue_summary"] == "Fix missing phone_number on Lead schema"
    assert context.triage_result["is_safe_to_apply"] is True
