"""Pure observation definitions do not establish accounting interpretation authority."""

# ruff: noqa:F811
from uuid import uuid4

import pytest
from test_definition_history import DB, item, retained  # noqa:F401

from finai_api.domain.ontology_catalog import canonical_id
from finai_api.services import function_execution, resources
from finai_api.services.accounting_consumption import _pure_observation_definition
from finai_api.services.workspace import WorkspaceError


def test_typed_observation_only_classification():
    definition = {
        "implementation_id": "ontology.object-set-derived/v1",
        "determinism": "DETERMINISTIC_FOR_PINNED_INPUTS",
        "code_sha256": "a" * 64,
        "dependency_sha256": "b" * 64,
    }
    attrs = {"object_set_id": str(uuid4()), "definition": definition}
    assert _pure_observation_definition(item("FunctionDefinition", attrs))
    for extra in [
        {"derived_property_ids": [str(uuid4())]},
        {"group_count": {"schema_id": str(uuid4()), "fields": ["source_family"]}},
        {"pure_observation": True},
        {"implementation_id": "unknown"},
    ]:
        assert not _pure_observation_definition(
            item("FunctionDefinition", {**attrs, "definition": {**definition, **extra}})
        )
    assert not _pure_observation_definition(item("DerivedProperty", attrs))
    assert not _pure_observation_definition(item("FunctionDefinition", {}))


@DB
def test_native_explicit_source_root_read_definition_and_calculation_refusal(retained):
    reader, publish = retained
    company = item("LegalEntity", {})
    chart = item(
        "LocalChartOfAccounts", {"legal_entity_id": str(company.resource_id), "code": "SYNTHETIC"}
    )
    account = item(
        "LocalAccount", {"chart_id": str(chart.resource_id), "account_code": "SYNTHETIC"}
    )
    evidence = item("SourceEvidence", {"sha256": uuid4().hex * 2, "source_system": "SYNTHETIC"})
    record = item(
        "SourceRecord", {"evidence_id": str(evidence.resource_id), "coordinate": "SYNTHETIC!3"}
    )
    movement = item(
        "SourceJournalMovement",
        {
            "legal_entity_id": str(company.resource_id),
            "debit_account_id": str(account.resource_id),
            "credit_account_id": str(account.resource_id),
            "source_record_id": str(record.resource_id),
            "posting_date": "2026-01-01",
            "document_reference": "SYNTHETIC",
            "amount": "1",
            "source_family": "SYNTHETIC",
            "source_row_key": "SYNTHETIC!3",
            "unit_status": "UNESTABLISHED",
            "source_details": {},
        },
    )
    publish(company, chart, account, evidence, record, movement)
    query = item(
        "ObjectSetDefinition",
        {
            "definition": {
                "object_type": "SourceJournalMovement",
                "resource_ids": [str(movement.resource_id)],
            }
        },
    )
    publish(query)
    manifest = function_execution.manifest()
    spec = {
        key: manifest[key]
        for key in ["implementation_id", "determinism", "code_sha256", "dependency_sha256"]
    }
    function = item(
        "FunctionDefinition", {"object_set_id": str(query.resource_id), "definition": spec}
    )
    accepted = publish(function)[0]
    assert accepted["authority_state"] == "APPROVED"
    with resources.resource_connection(reader) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM resource_dependencies d JOIN resource_versions v "
                "ON v.tenant_id=d.tenant_id AND v.version_id=d.target_version_id "
                "WHERE d.tenant_id=%s AND d.version_id=%s "
                "AND v.object_type='SourceAccountingBinding'",
                (reader.scope.tenant_id, accepted["version_id"]),
            ).fetchone()[0]
            == 0
        )
    derived = item(
        "DerivedProperty",
        {
            "schema_id": str(
                canonical_id(reader.scope.tenant_id, "SchemaDefinition", "SourceJournalMovement")
            ),
            "definition": {
                "name": "synthetic_amount",
                "result_kind": "decimal",
                "expression": {"op": "field", "field": "amount"},
            },
        },
    )
    publish(derived)
    calculating = item(
        "FunctionDefinition",
        {
            "object_set_id": str(query.resource_id),
            "definition": {**spec, "derived_property_ids": [str(derived.resource_id)]},
        },
    )
    with pytest.raises(WorkspaceError, match="exact SourceAccountingBinding"):
        publish(calculating)
