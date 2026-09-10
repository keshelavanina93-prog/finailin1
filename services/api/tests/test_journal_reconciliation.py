"""Synthetic accepted bundles exercise consumption; they grant no SEG acceptance."""
# ruff: noqa: F811

from copy import deepcopy
from uuid import uuid4

import pytest
from test_entity_movement_review import fixture
from test_semantic_entity_movements import case as workspace_case  # noqa: F401

from finai_api.services.entity_movement_review import review
from finai_api.services.journal_reconciliation import compile_reconciliation
from finai_api.services.workspace import WorkspaceError


def case():
    parsed, source, targets, ids = fixture()
    source["evidence"] = {"resource_id": str(uuid4())}
    source["binding"]["version_id"] = targets[source["binding"]["resource_id"]]["version_id"]
    # A synthetic supported profile, explicitly not the reviewed SEG profile.
    targets[ids["scope"]]["attributes"]["source_profile"] = "1c_journal"
    result = review(parsed, source, targets, {})
    pair = result["pairs"][0]
    entry = {
        "resource_id": pair["proposed_entry_id"],
        "version_id": str(uuid4()),
        "authority_state": "APPROVED",
        "valid_from": "2025-01-01",
        "valid_to": None,
        "attributes": deepcopy(pair["entry"]),
    }
    lines = []
    for original in pair["lines"]:
        account = targets[original["account"]["resource_id"]]
        lines.append(
            {
                "line": {
                    "resource_id": original["proposed_resource_id"],
                    "version_id": str(uuid4()),
                    "authority_state": "APPROVED",
                    "valid_from": entry["valid_from"],
                    "valid_to": None,
                    "attributes": {
                        "side": original["side"],
                        "amount": original["amount"],
                        "account_id": account["resource_id"],
                        "journal_id": entry["resource_id"],
                        "accounting_binding_id": source["binding"]["resource_id"],
                    },
                },
                "account": account,
                "source_record": {
                    "attributes": {
                        "coordinate": pair["source_coordinate"],
                        "evidence_id": source["evidence"]["resource_id"],
                    }
                },
                "dimensions": {"state": "COMPLETE", "policy": {"version_id": str(uuid4())}},
            }
        )
    detail = {
        "journal": entry,
        "binding": targets[source["binding"]["resource_id"]],
        "lines": lines,
        "integrity": {"issues": []},
        "selection": {},
        "snapshot_at": "2026-09-08T00:00:00+00:00",
    }
    return result, source, targets, detail, ids


def compile_case(data, details=None):
    result, source, targets, detail, _ = data
    return compile_reconciliation(
        result, source, targets, [detail] if details is None else details, {}, detail["snapshot_at"]
    )


def test_exact_accepted_bundle_movement_receipt_and_no_opening_closing():
    data = case()
    result = compile_case(data)
    assert result["status"] == "RECONCILED"
    assert (
        result["matched_source_amount"]
        == result["journal_debit_total"]
        == result["journal_credit_total"]
        == "731.97"
    )
    assert result["unmatched_source_amount"] == "0.00"
    assert {row["net_movement"] for row in result["movement_trial_balance"]} == {
        "731.97",
        "-731.97",
    }
    assert all(
        row["opening_balance"] is None and row["closing_balance"] is None
        for row in result["movement_trial_balance"]
    )
    assert result["accepted"][0]["source_coordinate"] == "Base!S2"
    assert compile_case(data) == result


def test_absent_journals_are_unavailable_not_zero():
    result = compile_case(case(), [])
    assert result["status"] == "UNAVAILABLE"
    assert result["movement_trial_balance"] is result["journal_debit_total"] is None
    assert result["missing_coordinates"] == ["Base!S2"]
    assert result["unmatched_source_amount"] == "731.97"


def test_reconciliation_controls_ignore_ambient_precision_and_exponent_limits():
    from decimal import Inexact, Rounded, localcontext

    data = case()
    expected = compile_case(data)
    with localcontext() as caller:
        caller.prec = 2
        caller.Emax = 1
        caller.Emin = -1
        caller.traps[Inexact] = caller.traps[Rounded] = True
        assert compile_case(data) == expected
        assert caller.prec == 2 and caller.Emax == 1


@pytest.mark.parametrize(
    "failure",
    [
        "profile",
        "policy",
        "amount",
        "side",
        "date",
        "account",
        "binding",
        "source",
        "excluded",
        "snapshot",
        "context",
        "missing_line",
    ],
)
def test_canonical_refusals_never_leak_into_trial_balance(failure):
    data = case()
    result, source, targets, detail, ids = data
    row = detail["lines"][0]
    if failure == "profile":
        targets[ids["scope"]]["attributes"]["source_profile"] = "seg_expense_base"
    elif failure == "policy":
        row["dimensions"]["state"] = "UNESTABLISHED"
    elif failure == "amount":
        row["line"]["attributes"]["amount"] = {
            **row["line"]["attributes"]["amount"],
            "amount": "731.96",
        }
    elif failure == "side":
        row["line"]["attributes"]["side"] = "CREDIT"
    elif failure == "date":
        detail["journal"]["attributes"]["posting_date"] = "2025-02-01"
    elif failure == "account":
        row["account"] = {**row["account"], "version_id": str(uuid4())}
    elif failure == "binding":
        detail["binding"] = {**detail["binding"], "version_id": str(uuid4())}
    elif failure == "source":
        row["source_record"]["attributes"]["evidence_id"] = str(uuid4())
    elif failure == "excluded":
        for line in detail["lines"]:
            line["source_record"]["attributes"]["coordinate"] = "Base!S288"
    elif failure == "snapshot":
        detail["snapshot_at"] = "2026-09-07T00:00:00+00:00"
        # Use an independently requested snapshot below.
    elif failure == "context":
        detail["selection"] = {"book_id": {"resource_id": str(uuid4())}}
    else:
        detail["lines"].pop()
    actual = compile_reconciliation(
        result, source, targets, [detail], {}, "2026-09-08T00:00:00+00:00"
    )
    assert actual["status"] == "UNAVAILABLE" and actual["movement_trial_balance"] is None
    assert len(actual["rejected"]) == 1 and not actual["accepted"]


def test_duplicate_journals_refused_instead_of_double_counting():
    data = case()
    with pytest.raises(WorkspaceError, match="Duplicate journal"):
        compile_case(data, [data[3], data[3]])


def test_partial_source_coverage_is_not_complete_trial_balance():
    data = case()
    data[0]["pairs"].append({**deepcopy(data[0]["pairs"][0]), "source_coordinate": "Base!S3"})
    data[0]["reconciliation"]["source_amount_total"] = "1463.94"
    result = compile_case(data)
    assert result["status"] == "PARTIAL" and result["unmatched_source_amount"] == "731.97"
    assert result["missing_coordinates"] == ["Base!S3"]


@pytest.mark.parametrize("failure", [None, "coverage", "context", "pagination", "unsupported"])
def test_existing_source_workspace_and_bounded_readback(workspace_case, monkeypatch, failure):
    from finai_api.services import journal_reconciliation as service

    history, request = workspace_case
    _, _plan, resolver = service.semantic_analysis.load(None, request.invocation_id)
    source = history["output"]["source_document"]
    original_field = resolver.field
    extra = {}

    def field(owner, key):
        try:
            return original_field(owner, key)
        except KeyError:
            assert key in {"chart_id", "calendar_id"}
            identity = owner["attributes"][key]
            return extra.setdefault(
                identity, {"resource_id": identity, "version_id": str(uuid4()), "attributes": {}}
            )

    monkeypatch.setattr(resolver, "field", field)
    monkeypatch.setattr(service.semantic_analysis, "load", lambda *_: (history, _plan, resolver))
    binding = resolver.version(source["binding"])
    scope = resolver.version(source["scope"])
    selected = {}
    for owner, fields in (
        (scope, ("legal_entity_id", "chart_id")),
        (binding, ("ledger_id", "book_id", "period_id", "currency_id")),
    ):
        for field in fields:
            selected[field] = service.resource_pin(resolver.field(owner, field))
    ledger = resolver.field(binding, "ledger_id")
    selected["calendar_id"] = service.resource_pin(resolver.field(ledger, "calendar_id"))
    if failure == "context":
        selected["book_id"]["version_id"] = str(uuid4())
    if failure == "unsupported":
        del history["output"]["entity_movement_review"]
    monkeypatch.setattr(service, "require_permission", lambda *_: None)
    page = {
        "selection": selected,
        "items": [],
        "next_offset": 0 if failure == "pagination" else None,
        "coverage": {"state": "UNRESOLVED" if failure == "coverage" else "COMPLETE"},
    }
    monkeypatch.setattr(service.company_journals, "list_journals", lambda *a, **kw: page)
    if failure:
        with pytest.raises(WorkspaceError):
            service.reconcile(None, request.invocation_id, request.company_id)
    else:
        result = service.reconcile(None, request.invocation_id, request.company_id)
        assert result["source_projection"].descriptor.contract == "semantic-analysis/2"
        assert len(result["source_projection"].rows) == 2
        for key in ("ledger_id", "book_id", "period_id"):
            row = resolver.version(selected[key])
            assert result["context_resources"][key] == {
                **selected[key],
                "display_name": row["display_name"],
            }
        assert result["reconciliation"]["journal_debit_total"] is None
