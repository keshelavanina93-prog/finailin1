from uuid import uuid4

import pytest

from finai_api.services.company_context import project, select_accounting
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
            },
        },
    ]
    pins = {
        ("b1", "reporter_id"): "c1",
        ("b1", "related_entity_id"): "p1",
        ("b1", "observation_id"): "o1",
    }
    result = project(nodes, pins, company)["context"]
    assert len(result["disclosures"]) == 1
    assert result["relationships"] == []
    assert len(result["structural_resources"]) == 1
