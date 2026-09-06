from uuid import uuid4

import pytest

from finai_api.services.company_context import (
    inspect_binding_eligibility,
    project,
    select_accounting,
)
from finai_api.services.workspace import WorkspaceError


def test_workspace_pins_and_company_ledger_boundaries():
    nodes, pins = [], {}

    def node(kind, **attrs):
        value = {
            "resource_id": str(uuid4()),
            "version_id": str(uuid4()),
            "object_type": kind,
            "attributes": attrs,
            "display_name": kind,
        }
        nodes.append(value)
        return value

    def ref(source, field, target):
        source["attributes"][field] = target["resource_id"]
        pins[source["version_id"], field] = target["version_id"]

    company, other = node("LegalEntity"), node("LegalEntity")
    workspace = node("CompanyWorkspace")
    ref(workspace, "company_id", company)
    ref(workspace, "enterprise_id", node("EnterpriseGroup"))
    ref(workspace, "domain_pack_id", node("DomainPack"))
    calendar, chart, currency = (
        node("FiscalCalendar"),
        node("LocalChartOfAccounts"),
        node("Currency"),
    )
    ledger = node("Ledger")
    for field, target in (
        ("legal_entity_id", company),
        ("calendar_id", calendar),
        ("chart_id", chart),
        ("currency_id", currency),
    ):
        ref(ledger, field, target)
    book, period = node("AccountingBook"), node("FiscalPeriod")
    ref(book, "ledger_id", ledger)
    ref(period, "calendar_id", calendar)
    result = project(nodes, pins, company["resource_id"])
    assert len(result["workspaces"]) == 1
    selected = select_accounting(
        result, ledger["resource_id"], book["resource_id"], period["resource_id"]
    )
    assert selected["legal_entity_id"]["resource_id"] == company["resource_id"]
    other_result = project(nodes, pins, other["resource_id"])
    with pytest.raises(WorkspaceError, match="not configured"):
        select_accounting(
            other_result, ledger["resource_id"], book["resource_id"], period["resource_id"]
        )
    with pytest.raises(WorkspaceError, match="Book or period"):
        select_accounting(result, ledger["resource_id"], str(uuid4()), period["resource_id"])
    # A changed company version cannot inherit workspace or ledger pins silently.
    company["version_id"] = str(uuid4())
    stale = project(nodes, pins, company["resource_id"])
    assert stale["workspaces"] == []
    assert stale["context"]["ledgers"] == []


def test_disclosed_subsidiaries_are_not_current_ownership_or_consolidation():
    company, party, observation, binding = [str(uuid4()) for _ in range(4)]
    nodes = [
        {
            "resource_id": company,
            "version_id": "c1",
            "object_type": "LegalEntity",
            "attributes": {},
        },
        {"resource_id": party, "version_id": "p1", "object_type": "LegalEntity", "attributes": {}},
        {
            "resource_id": observation,
            "version_id": "o1",
            "object_type": "SourceCorporateObservation",
            "attributes": {
                "observation": {"reported_role": "SUBSIDIARY", "reported_percent": "100"}
            },
        },
        {
            "resource_id": binding,
            "version_id": "b1",
            "object_type": "CorporateDisclosureBinding",
            "attributes": {
                "reporter_id": company,
                "related_entity_id": party,
                "observation_id": observation,
                "reporting_year": 2024,
            },
        },
    ]
    pins = {
        ("b1", "reporter_id"): "c1",
        ("b1", "related_entity_id"): "p1",
        ("b1", "observation_id"): "o1",
    }
    projection = project(nodes, pins, company)
    assert projection["reported_groups"][0]["reporting_year"] == 2024
    assert projection["reported_groups"][0]["members"][0]["company"]["resource_id"] == party
    result = projection["context"]
    assert len(result["disclosures"]) == 1
    assert result["relationships"] == []
    assert len(result["structural_resources"]) == 1


def test_reviewed_selection_retains_exact_older_scope_without_rebinding():
    company = {
        "resource_id": "company",
        "version_id": "company-v1",
        "object_type": "LegalEntity",
        "attributes": {},
    }
    scope = {
        "resource_id": "scope",
        "version_id": "scope-v2",
        "object_type": "SourceAccountingScope",
        "attributes": {"legal_entity_id": "company"},
    }
    historical = {**scope, "version_id": "scope-v1"}
    binding = {
        "resource_id": "binding",
        "version_id": "binding-v1",
        "object_type": "SourceAccountingBinding",
        "attributes": {"scope_id": "scope"},
    }
    pins = {("scope-v2", "legal_entity_id"): "company-v1", ("binding-v1", "scope_id"): "scope-v1"}
    nodes = [company, scope, binding]
    result = project(nodes, pins, "company", [historical])
    source = result["context"]["accounting_sources"][0]
    assert source["scope"]["version_id"] == "scope-v2"
    assert source["bindings"] == [binding]
    assert pins["binding-v1", "scope_id"] == "scope-v1"
    # An attribute alone, missing retained pin, different identity or wrong type is not proof.
    for targets in (
        [],
        [{**historical, "resource_id": "other"}],
        [{**historical, "object_type": "LegalEntity"}],
    ):
        assert (
            project(nodes, pins, "company", targets)["context"]["accounting_sources"][0]["bindings"]
            == []
        )
    assert project(nodes, {}, "company", [historical])["context"]["accounting_sources"] == []
    owner_pin_only = {("scope-v2", "legal_entity_id"): "company-v1"}
    assert (
        project(nodes, owner_pin_only, "company", [historical])["context"]["accounting_sources"][0][
            "bindings"
        ]
        == []
    )


def test_current_eligibility_uses_shared_guard_and_preserves_reviewed_selection(monkeypatch):
    from finai_api.services import accounting_binding_status

    binding = {"version_id": "retained-version", "attributes": {"source_use": "ACCOUNTING_INPUT"}}
    status = {
        "state": "CURRENT_USE_BLOCKED",
        "checked_at": "2026-09-07T00:00:00+00:00",
        "current_use_authorized": False,
        "reason": "Upstream scope superseded",
    }
    calls = []

    def inspect(principal, selected):
        calls.append((principal, selected))
        return status

    monkeypatch.setattr(accounting_binding_status, "inspect", inspect)
    source = {"scope": {}, "bindings": [binding]}
    result = {"context": {"accounting_sources": [source]}, "valid_at": "2025-01-01"}
    inspect_binding_eligibility("principal", result)
    assert calls == [("principal", binding)]
    assert source["bindings"] == [binding]
    assert source["binding_eligibility"] == {"retained-version": status}
    assert result["valid_at"] == "2025-01-01"


def test_company_eligibility_check_bound_is_explicit_and_never_grants_use(monkeypatch):
    from finai_api.services import accounting_binding_status

    calls = []

    def inspect(principal, selected):
        calls.append(selected)
        return {"state": "NOT_ACCOUNTING_INPUT", "current_use_authorized": False}

    monkeypatch.setattr(accounting_binding_status, "inspect", inspect)
    source = {"bindings": [{"version_id": str(i), "attributes": {}} for i in range(101)]}
    inspect_binding_eligibility(None, {"context": {"accounting_sources": [source]}})
    assert len(calls) == 100
    unchecked = source["binding_eligibility"]["100"]
    assert unchecked["state"] == "ELIGIBILITY_NOT_CHECKED"
    assert unchecked["checked_at"] is None
    assert unchecked["current_use_authorized"] is False
    assert unchecked["eligible_for_accounting"] is False
