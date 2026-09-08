"""Scoped policy semantics; native relationship guards are exercised separately."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from finai_api.services import journal_dimensions as core
from finai_api.services.workspace import WorkspaceError


def test_scoped_policy_chart_evidence_and_book_period_are_exact(monkeypatch):
    nodes = {}

    def node(kind, **attrs):
        record = {
            "resource_id": str(uuid4()),
            "version_id": str(uuid4()),
            "object_type": kind,
            "authority_state": "APPROVED",
            "evidence_class": "USER_ASSERTED",
            "attributes": attrs,
        }
        nodes[record["resource_id"]] = record
        return record

    company = node("LegalEntity")
    chart = node("LocalChartOfAccounts", legal_entity_id=company["resource_id"])
    account = node("LocalAccount", chart_id=chart["resource_id"], account_code="SYNTHETIC")
    book, period, evidence = node("AccountingBook"), node("FiscalPeriod"), node("SourceEvidence")
    observed = node(
        "SourceAccountDefinition",
        account_code="SYNTHETIC",
        evidence_id=evidence["resource_id"],
        definition={"analytics": []},
    )
    context = {
        name: core.pin(n)
        for name, n in [
            ("company", company),
            ("chart", chart),
            ("book", book),
            ("period", period),
            ("source_account", observed),
            ("evidence", evidence),
        ]
    }
    context.update(state="EXPLICIT_NO_ADDITIONAL_DIMENSIONS", additional_dimensions="PROHIBITED")
    policy = node(
        "AccountDimensionPolicy",
        account_id=account["resource_id"],
        chart_id=chart["resource_id"],
        legal_entity_id=company["resource_id"],
        definition={
            "contract": "account-dimension-policy/1",
            "reason": "Reviewed synthetic empty chart analytics",
            "rules": [],
            "context": context,
        },
    )
    monkeypatch.setattr(core, "edge", lambda *_: None)
    monkeypatch.setattr(core, "complete", lambda *_: None)

    def target(key, *_):
        return nodes[key]

    assert core.inspect_policy(None, None, policy, account, target, None) == {}
    observed["attributes"]["definition"]["analytics"] = [{"source_label": "Required analytic"}]
    with pytest.raises(WorkspaceError, match="chart analytics"):
        core.inspect_policy(None, None, policy, account, target, None)
    observed["attributes"]["definition"]["analytics"] = []
    observed["attributes"]["account_code"] = "OTHER"
    with pytest.raises(WorkspaceError, match="another account"):
        core.inspect_policy(None, None, policy, account, target, None)
    observed["attributes"]["account_code"] = "SYNTHETIC"
    binding = node(
        "SourceAccountingBinding", book_id=book["resource_id"], period_id=period["resource_id"]
    )
    line = SimpleNamespace(
        resource_id=uuid4(),
        attributes={
            "account_id": account["resource_id"],
            "accounting_binding_id": binding["resource_id"],
            "dimension_policy_id": policy["resource_id"],
            "dimensions": {
                "contract": "journal-line-dimensions/1",
                "policy": core.pin(policy),
                "assignments": [],
            },
        },
    )
    proposal = SimpleNamespace(mutations=[])
    core.validate_line(None, None, line, target, proposal, None)
    binding["attributes"]["book_id"] = node("AccountingBook")["resource_id"]
    with pytest.raises(WorkspaceError, match="book or period"):
        core.validate_line(None, None, line, target, proposal, None)
    book["version_id"] = str(uuid4())
    with pytest.raises(WorkspaceError, match="context version changed"):
        core.inspect_policy(None, None, policy, account, target, None)
    context["state"] = "REVIEWED_RULE_SET"
    with pytest.raises(WorkspaceError, match="declaration differs"):
        core.inspect_policy(None, None, policy, account, target, None)
