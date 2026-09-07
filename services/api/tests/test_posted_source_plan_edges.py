"""Exact posting inputs cannot bypass reviewed source, account or knowledge-time pins."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from test_seg_expense_source import workbook

from finai_api.domain.function_execution import FunctionDefinition
from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.services import posted_movements_function as posted
from finai_api.services.seg_expense_source import read_base
from finai_api.services.workspace import WorkspaceError

NOW = datetime(2026, 9, 8, tzinfo=UTC)


@pytest.fixture
def case(monkeypatch):
    content = workbook()
    parsed = read_base(content)
    ids = {
        name: str(uuid4())
        for name in (
            "binding",
            "scope",
            "evidence",
            "company",
            "chart",
            "accounts",
            "dimensions",
            "account",
            "credit",
        )
    }
    pins = {}

    def row(name, kind, attributes):
        result = {
            "resource_id": ids[name],
            "version_id": str(uuid4()),
            "content_hash": "a" * 64,
            "object_type": kind,
            "attributes": attributes,
            "system_from": NOW - timedelta(days=1),
        }
        pins[ids[name]] = result
        return result

    account = row("account", "LocalAccount", {"chart_id": ids["chart"], "account_code": "0012.01"})
    credit = row("credit", "LocalAccount", {"chart_id": ids["chart"], "account_code": "3110"})
    row(
        "accounts",
        "Mapping",
        {
            "definition": {
                "kind": "EXACT_SOURCE_ACCOUNT_IDENTITIES",
                "version": 1,
                "company_id": ids["company"],
                "chart_id": ids["chart"],
                "accounts": {
                    "0012.01": {
                        "resource_id": account["resource_id"],
                        "version_id": account["version_id"],
                    },
                    "3110": {
                        "resource_id": credit["resource_id"],
                        "version_id": credit["version_id"],
                    },
                },
            }
        },
    )
    row(
        "dimensions",
        "Mapping",
        {
            "definition": {
                "kind": "PRESERVE_SOURCE_DIMENSION_COORDINATES",
                "company_id": ids["company"],
                "aggregation_dimensions": [],
            }
        },
    )
    context = {
        name: str(uuid4())
        for name in (
            "ledger_id",
            "book_id",
            "period_id",
            "currency_id",
            "functional_currency_id",
        )
    }
    context.update(
        amount_field="source_amount", amount_semantics="AS_POSTED", vat_treatment="AS_POSTED"
    )
    binding = row(
        "binding",
        "SourceAccountingBinding",
        {
            **context,
            "scope_id": ids["scope"],
            "account_mapping_id": ids["accounts"],
            "dimension_mapping_id": ids["dimensions"],
        },
    )
    row(
        "scope",
        "SourceAccountingScope",
        {
            "evidence_id": ids["evidence"],
            "document_id": "doc_" + "b" * 64,
            "worksheet": "Base",
            "source_profile": "seg_expense_base",
            "legal_entity_id": ids["company"],
            "chart_id": ids["chart"],
            "observed_from": "2025-01-01",
            "observed_through": "2025-01-31",
        },
    )
    row("evidence", "SourceEvidence", {"sha256": parsed["source_sha256"]})
    spec = FunctionDefinition.model_validate(
        {
            "accounting_binding_id": ids["binding"],
            "source_scope_id": ids["scope"],
            "evidence_id": ids["evidence"],
            "minimum_authority_state": "OBSERVED",
            "definition": {
                "implementation_id": "accounting.retained-posted-movements/v1",
                "determinism": "DETERMINISTIC_FOR_PINNED_INPUTS",
                "code_sha256": "c" * 64,
                "dependency_sha256": "d" * 64,
                "document_id": "doc_" + "b" * 64,
                "source_sha256": parsed["source_sha256"],
                "sheet": "Base",
                "max_source_rows": 10,
            },
        }
    )
    selection = Mock()
    authority = Mock()
    metadata = {
        "document_id": spec.definition.document_id,
        "filename": "synthetic.xlsx",
        "source_sha256": parsed["source_sha256"],
        "source_snapshot": {"ingested_at": (NOW - timedelta(days=1)).isoformat()},
    }
    source = Mock(return_value=(metadata, content))
    monkeypatch.setattr(posted, "validate_active_selection", selection)
    monkeypatch.setattr(posted, "require_accounting_bindings", authority)
    monkeypatch.setattr(posted, "read_source", source)
    request = SimpleNamespace(
        offset=0,
        input_result=None,
        known_at=NOW,
        function=VersionReference(resource_id=uuid4(), version_id=uuid4()),
    )
    return SimpleNamespace(
        ids=ids,
        pins=pins,
        spec=spec,
        source=source,
        metadata=metadata,
        request=request,
        authority=authority,
        selection=selection,
        binding=binding,
        parsed=parsed,
    )


def test_source_plan_retains_reviewed_context_and_exact_dependencies(case):
    plan = posted.source_plan("reader", case.request, case.spec, case.pins)
    assert plan["company_id"] == case.ids["company"] and plan["row_count"] == 1
    assert plan["context"]["amount_semantics"] == "AS_POSTED"
    assert plan["binding"]["version_id"] == case.binding["version_id"]
    case.selection.assert_called_once()
    attrs, source, resolve = case.selection.call_args.args
    scope = case.pins[case.ids["scope"]]
    assert attrs == case.binding["attributes"]
    assert source == scope["attributes"]
    for identity, pin in case.pins.items():
        assert resolve(identity) is pin
    case.authority.assert_called_once_with(
        "reader",
        {(UUID(scope["resource_id"]), UUID(scope["version_id"]))},
        {(UUID(pin["resource_id"]), UUID(pin["version_id"])) for pin in case.pins.values()},
    )
    case.source.assert_called_once_with("reader", case.spec.definition.document_id)
    assert plan["accounts"]["0012.01"]["version_id"] == case.pins[case.ids["account"]]["version_id"]


@pytest.mark.parametrize(
    "subject,field,value",
    [
        ("binding", "scope_id", "foreign"),
        ("scope", "evidence_id", "foreign"),
        ("scope", "document_id", "foreign"),
        ("scope", "worksheet", "Other"),
        ("scope", "source_profile", "unknown"),
        ("evidence", "sha256", "0" * 64),
        ("account", "account_code", "other"),
        ("account", "chart_id", "foreign"),
    ],
)
def test_definition_refuses_mixed_source_or_account_identity_before_source_read(
    case, subject, field, value
):
    case.pins[case.ids[subject]]["attributes"][field] = value
    with pytest.raises(WorkspaceError) as rejected:
        posted.source_plan("reader", case.request, case.spec, case.pins)
    assert rejected.value.status == 409
    case.source.assert_not_called()


@pytest.mark.parametrize(
    "subject,field,value",
    [
        ("accounts", "kind", "NUMERIC_SUM"),
        ("accounts", "version", 2),
        ("accounts", "company_id", "foreign"),
        ("accounts", "chart_id", "foreign"),
        ("accounts", "accounts", {}),
        ("dimensions", "kind", "FLATTEN"),
        ("dimensions", "aggregation_dimensions", ["unreviewed"]),
        ("dimensions", "company_id", "foreign"),
    ],
)
def test_mapping_changes_require_reviewed_exact_rules(case, subject, field, value):
    case.pins[case.ids[subject]]["attributes"]["definition"][field] = value
    with pytest.raises(WorkspaceError, match="reviewed exact source mapping"):
        posted.source_plan("reader", case.request, case.spec, case.pins)
    case.source.assert_not_called()


@pytest.mark.parametrize(
    "change", ["offset", "input", "pin", "known", "hash", "retained", "rows", "duplicate"]
)
def test_planning_refuses_partial_future_changed_or_unreviewed_input(case, monkeypatch, change):
    if change == "offset":
        case.request.offset = 1
    elif change == "input":
        case.request.input_result = object()
    elif change == "pin":
        del case.pins[case.ids["scope"]]
    elif change == "known":
        case.binding["system_from"] = NOW + timedelta(seconds=1)
    elif change == "hash":
        case.metadata["source_sha256"] = "0" * 64
    elif change == "retained":
        case.metadata["source_snapshot"]["ingested_at"] = (NOW + timedelta(seconds=1)).isoformat()
    else:
        parsed = deepcopy(case.parsed)
        if change == "rows":
            parsed["rows"] *= 11
        else:
            parsed["posting_identity_ready"] = False
        monkeypatch.setattr(posted, "read_base", lambda *_: parsed)
    with pytest.raises(WorkspaceError) as rejected:
        posted.source_plan("reader", case.request, case.spec, case.pins)
    assert rejected.value.status in (409, 422)
    if change in {"offset", "input", "pin", "known"}:
        case.source.assert_not_called()


def test_execution_keeps_exact_amount_and_requires_current_consumption_proof(case, monkeypatch):
    source = posted.source_plan("reader", case.request, case.spec, case.pins)
    case.request.valid_at = NOW
    case.request.limit = 50
    plan = {
        "source_document": source,
        "static_dependencies": [source["scope"], source["binding"]],
        "function": case.request.function.model_dump(mode="json"),
        "implementation": case.spec.definition.model_dump(mode="json"),
        "plan_hash": "e" * 64,
    }
    proof = Mock(return_value={"consumption_id": "fixture-consumption", "proof_hash": "f" * 64})
    monkeypatch.setattr(posted, "consume", proof)
    result = posted.execute("reader", case.request, plan)
    assert result["authority_check"]["proof_hash"] == "f" * 64
    assert [row["value"] for row in result["posted_movements"]["groups"]] == ["731.97", "731.97"]
    assert result["posted_movements"]["coverage"]["ledger_completeness"] == "UNESTABLISHED"
    assert (
        result["business_effect_authorized"] is False and result["current_use_authorized"] is False
    )
    request = proof.call_args.args[1]
    assert request.minimum_state == "OBSERVED" and len(request.inputs) == 2
    proof.side_effect = WorkspaceError(409, "Reviewed input revoked")
    with pytest.raises(WorkspaceError, match="revoked"):
        posted.execute("reader", case.request, plan)
    proof.reset_mock()
    case.metadata["source_sha256"] = "0" * 64
    with pytest.raises(WorkspaceError, match="hash changed"):
        posted.execute("reader", case.request, plan)
    proof.assert_not_called()
