"""Publication compatibility uses the same active interpretation as consumption."""

from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_accounting_consumption import fixture_graph

from finai_api.services.accounting_promotion import validate_journal
from finai_api.services.workspace import WorkspaceError


def journal_fixture():
    rows, _, _, _, _, binding_key = fixture_graph()
    nodes = {
        str(key[0]): {**row, "resource_id": str(key[0]), "version_id": str(key[1])}
        for key, row in rows.items()
    }
    binding = nodes[str(binding_key[0])]
    config = binding["attributes"]
    scope = nodes[config["scope_id"]]["attributes"]
    entry_id, account_id, record_id = [str(uuid4()) for _ in range(3)]
    entry = {
        "accounting_binding_id": str(binding_key[0]),
        "legal_entity_id": scope["legal_entity_id"],
        "ledger_id": config["ledger_id"],
        "period_id": config["period_id"],
    }
    nodes[entry_id] = {"object_type": "JournalEntry", "attributes": entry}
    nodes[account_id] = {
        "object_type": "LocalAccount",
        "attributes": {"chart_id": scope["chart_id"]},
    }
    nodes[record_id] = {
        "object_type": "SourceRecord",
        "attributes": {"evidence_id": scope["evidence_id"]},
    }
    line = {
        "accounting_binding_id": str(binding_key[0]),
        "journal_id": entry_id,
        "account_id": account_id,
        "source_record_id": record_id,
        "amount": {"amount": "12", "currency_id": config["currency_id"]},
    }
    return nodes, entry, line, binding


def item(kind, attrs):
    return SimpleNamespace(object_type=kind, attributes=attrs, resource_id=uuid4())


def test_compatible_entry_and_line_resolve_shared_binding():
    nodes, entry, line, binding = journal_fixture()
    visited = []

    def target(identity, *_):
        visited.append(identity)
        return nodes[identity]

    assert validate_journal(item("JournalEntry", entry), target) == binding
    assert validate_journal(item("JournalLine", line), target) == binding
    assert entry["accounting_binding_id"] in visited
    assert line["source_record_id"] in visited


@pytest.mark.parametrize("field", ["legal_entity_id", "ledger_id", "period_id"])
def test_wrong_company_ledger_or_period_rejected(field):
    nodes, entry, _, _ = journal_fixture()
    entry[field] = str(uuid4())
    with pytest.raises(WorkspaceError):
        validate_journal(item("JournalEntry", entry), lambda identity, *_: nodes[identity])


@pytest.mark.parametrize("change", ["chart", "evidence", "currency", "parent_company"])
def test_incompatible_line_source_or_parent_rejected(change):
    nodes, _, line, _ = journal_fixture()
    if change == "chart":
        nodes[line["account_id"]]["attributes"]["chart_id"] = str(uuid4())
    elif change == "evidence":
        nodes[line["source_record_id"]]["attributes"]["evidence_id"] = str(uuid4())
    elif change == "currency":
        line["amount"]["currency_id"] = str(uuid4())
    else:
        nodes[line["journal_id"]]["attributes"]["legal_entity_id"] = str(uuid4())
    with pytest.raises(WorkspaceError):
        validate_journal(item("JournalLine", line), lambda identity, *_: nodes[identity])


@pytest.mark.parametrize("kind", ["JournalEntry", "JournalLine"])
def test_missing_binding_and_review_candidate_cannot_publish(kind):
    nodes, entry, line, binding = journal_fixture()
    attrs = entry if kind == "JournalEntry" else line
    missing = deepcopy(attrs)
    missing.pop("accounting_binding_id")
    with pytest.raises(WorkspaceError, match="binding"):
        validate_journal(item(kind, missing), lambda identity, *_: nodes[identity])
    binding["attributes"]["source_use"] = "REVIEW_CANDIDATE"
    with pytest.raises(WorkspaceError):
        validate_journal(item(kind, attrs), lambda identity, *_: nodes[identity])


@pytest.mark.parametrize("include_binding", [True, False])
def test_custom_typed_accounting_derivation_requires_accepted_binding(monkeypatch, include_binding):
    from finai_api.domain.resources import ResourceMutation, ResourceProposal
    from finai_api.services import accounting_consumption as guard

    rows, edges, _, _, source, binding = fixture_graph()
    mutation = ResourceMutation(
        object_type="CustomAccountingFact",
        identity_key="synthetic-derived-promotion",
        display_name="Synthetic derived fact",
        attributes={"amount": "12"},
        valid_from=datetime.now(UTC),
        evidence_class="SOURCE_BOUND",
    )
    proposal = ResourceProposal(
        title="Synthetic derived proposal",
        rationale="Validate immutable accounting ancestry",
        access_entity="synthetic",
        mutations=[mutation],
    )
    dependencies = {
        str(mutation.resource_id): [
            {
                "resource_id": str(source[0]),
                "version_id": str(source[1]),
                "relation": "FIELD:source_id",
            }
        ]
    }
    if include_binding:
        dependencies[str(mutation.resource_id)].append(
            {
                "resource_id": str(binding[0]),
                "version_id": str(binding[1]),
                "relation": "FIELD:accounting_binding_id",
            }
        )
    monkeypatch.setattr(guard, "load_accounting_lineage", lambda *_: (deepcopy(rows), list(edges)))
    material_checks = []
    monkeypatch.setattr(
        "finai_api.services.accounting_promotion.validate_current_binding",
        lambda _conn, _principal, value: material_checks.append(value),
    )
    if include_binding:
        guard.validate_accounting_proposal(None, None, proposal, dependencies)
        assert len(material_checks) == 1
    else:
        with pytest.raises(WorkspaceError, match="direct consumer dependency"):
            guard.validate_accounting_proposal(None, None, proposal, dependencies)


@pytest.mark.parametrize("representation", ["consumer", "hidden_measure", "undeclared_flag"])
def test_calculation_consumer_is_schema_declared_and_measure_free(monkeypatch, representation):
    from finai_api.domain.resources import ResourceMutation, ResourceProposal
    from finai_api.services import accounting_consumption as guard

    rows, edges, facts, _, _, binding = fixture_graph()
    schema, contract = (uuid4(), uuid4()), (uuid4(), uuid4())
    fields = {"minimum_authority_state": {"kind": "identifier"}}
    attrs = {"minimum_authority_state": "PARSED"}
    if representation == "hidden_measure":
        fields["net_amount"] = {"kind": "decimal"}
        attrs["net_amount"] = "120000"
    if representation == "undeclared_flag":
        fields.clear()
    rows[schema] = {"object_type": "SchemaDefinition", "attributes": {"fields": fields}}
    rows[contract] = {
        "object_type": "FactContract",
        "attributes": {"definition": {"measure": "amount", "unit_field": "unit"}},
    }
    mutation = ResourceMutation(
        object_type="AccountingCalculation",
        identity_key="synthetic-consumer",
        display_name="Synthetic calculation",
        attributes=attrs,
        valid_from=datetime.now(UTC),
    )
    proposal = ResourceProposal(
        title="Synthetic accounting consumer",
        rationale="Accept a measure-free accounting calculation contract",
        access_entity="synthetic",
        mutations=[mutation],
    )
    pins = [*facts, binding, schema, contract]
    dependencies = {
        str(mutation.resource_id): [
            {
                "resource_id": str(pin[0]),
                "version_id": str(pin[1]),
                "relation": "USES_SCHEMA" if pin == schema else "FIELD:input",
            }
            for pin in pins
        ]
    }
    monkeypatch.setattr(guard, "load_accounting_lineage", lambda *_: (deepcopy(rows), list(edges)))
    checks = []
    monkeypatch.setattr(
        "finai_api.services.accounting_promotion.validate_current_binding",
        lambda *_: checks.append(True),
    )
    if representation == "consumer":
        guard.validate_accounting_proposal(None, None, proposal, dependencies)
        assert checks == [True]
    else:
        with pytest.raises(WorkspaceError, match="measure"):
            guard.validate_accounting_proposal(None, None, proposal, dependencies)


def test_raw_dimension_observation_remains_publishable_without_active_binding(monkeypatch):
    from finai_api.domain.resources import ResourceMutation, ResourceProposal
    from finai_api.services import accounting_consumption as guard

    mutation = ResourceMutation(
        object_type="SourceDimensionAssignment",
        identity_key="synthetic-dimension",
        display_name="Synthetic observed dimension",
        attributes={},
        valid_from=datetime.now(UTC),
        evidence_class="SOURCE_BOUND",
    )
    proposal = ResourceProposal(
        title="Retain raw source dimension",
        rationale="Observation is not financial accounting acceptance",
        access_entity="synthetic",
        mutations=[mutation],
    )
    monkeypatch.setattr(
        guard, "load_accounting_lineage", lambda *_: pytest.fail("raw observation exemption")
    )
    guard.validate_accounting_proposal(None, None, proposal, {})
