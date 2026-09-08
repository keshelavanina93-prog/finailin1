"""Supported company/account metrics with exact scope and conservative coverage."""
# ruff: noqa: F811

from copy import deepcopy
from datetime import datetime
from decimal import Inexact, localcontext
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_semantic_entity_movements import case as workspace_case  # noqa: F401

from finai_api.domain.company_financial_metrics import FinancialMetricRequest, MetricValue
from finai_api.services import company_financial_metrics as metrics
from finai_api.services import semantic_analysis
from finai_api.services.entity_movement_review import digest
from finai_api.services.workspace import WorkspaceError


@pytest.fixture
def metric_case(workspace_case):
    history, original_request = workspace_case
    projection = semantic_analysis.project(None, original_request)
    _, _, resolver = semantic_analysis.load(None, original_request.invocation_id)
    source = history["output"]["source_document"]
    scope = resolver.version(source["scope"])
    ids = {
        **source["context"],
        "legal_entity_id": source["company_id"],
        "chart_id": scope["attributes"]["chart_id"],
    }
    ids["calendar_id"] = resolver.version({"resource_id": ids["ledger_id"]})["attributes"][
        "calendar_id"
    ]
    selected = {
        key: {
            k: str(resolver.version({"resource_id": ids[key]})[k])
            for k in ("resource_id", "version_id")
        }
        for key in (
            "legal_entity_id",
            "ledger_id",
            "book_id",
            "period_id",
            "currency_id",
        )
    }
    selected["calendar_id"] = {"resource_id": ids["calendar_id"], "version_id": str(uuid4())}
    selected["chart_id"] = {"resource_id": ids["chart_id"], "version_id": str(uuid4())}
    review = history["output"]["entity_movement_review"]
    pair = review["pairs"][0]
    entry = {
        "journal": {"resource_id": pair["proposed_entry_id"], "version_id": str(uuid4())},
        "source_coordinate": "Base!S2",
        "lines": [
            {
                "line": {"resource_id": line["proposed_resource_id"], "version_id": str(uuid4())},
                "dimensions": {
                    "state": "COMPLETE",
                    "policy": {"resource_id": str(uuid4()), "version_id": str(uuid4())},
                },
            }
            for line in pair["lines"]
        ],
    }
    receipt = {
        "contract": "source-journal-movement-reconciliation/1",
        "basis": "EXACT_SOURCE_MATCHED_CANONICAL_JOURNALS",
        "selection": selected,
        "snapshot_at": "2026-09-08T00:00:00+00:00",
        "binding": source["binding"],
        "source_sha256": source["sha256"],
        "source_receipt_hash": review["reconciliation"]["receipt_hash"],
        "status": "RECONCILED",
        "accepted": [entry],
        "missing_coordinates": [],
        "excluded_rows": [],
        "rejected": [],
        "movement_trial_balance": review["movements"],
        "matched_source_amount": "731.97",
        "journal_debit_total": "731.97",
        "journal_credit_total": "731.97",
    }
    request = FinancialMetricRequest(
        invocation_id=original_request.invocation_id,
        company_id=original_request.company_id,
        snapshot_at=datetime.fromisoformat(receipt["snapshot_at"]),
    )
    return request, receipt, projection


def run(data):
    request, receipt, projection = data
    receipt["receipt_hash"] = digest({k: v for k, v in receipt.items() if k != "receipt_hash"})
    return metrics.compute(request, receipt, projection)


def test_company_and_account_hierarchy_has_exact_derived_values(metric_case):
    result = run(metric_case)
    root, *accounts = result.nodes
    assert root.metrics["debit_movement"].value == root.metrics["credit_movement"].value == "731.97"
    assert (
        root.metrics["net_movement"].state == "VALUE"
        and root.metrics["net_movement"].value == "0.00"
    )
    assert {r.metrics["net_movement"].value for r in accounts} == {"731.97", "-731.97"}
    assert all(r.parent_key == root.key and r.source_coordinates == ["Base!S2"] for r in accounts)
    assert result.coverage.ledger_completeness == "UNESTABLISHED"
    assert len(result.journals[0].lines) == 2 and all(
        d.definition_authority == "CODE_DEFINED_NOT_PUBLISHED" for d in result.definitions
    )
    assert result.source_function == metric_case[2].descriptor.function
    assert not result.current_use_authorized and "FINANCIAL_STATEMENTS" in result.unavailable
    assert run(metric_case) == result
    reversed_input = deepcopy(metric_case)
    reversed_input[1]["movement_trial_balance"].reverse()
    reordered = run(reversed_input)
    assert reordered.nodes == result.nodes


def test_partial_excluded_and_missing_coverage_remains_visible(metric_case):
    receipt = metric_case[1]
    receipt.update(
        status="PARTIAL",
        missing_coordinates=["Base!S17"],
        excluded_rows=[{"coordinate": "Base!S288", "reason": "MISSING_LITERAL_POSTED_AMOUNT"}],
    )
    result = run(metric_case)
    assert result.coverage.source_rows == 3 and result.coverage.literal_source_rows == 2
    assert (
        result.coverage.accepted_journals
        == result.coverage.unmatched_source_rows
        == result.coverage.excluded_source_rows
        == 1
    )
    assert result.nodes[0].metrics["debit_movement"].value == "731.97"


def test_no_accepted_journal_returns_unavailable_not_zero(metric_case):
    metric_case[1].update(
        status="UNAVAILABLE",
        accepted=[],
        missing_coordinates=["Base!S2"],
        movement_trial_balance=None,
        matched_source_amount=None,
        journal_debit_total=None,
        journal_credit_total=None,
    )
    result = run(metric_case)
    assert len(result.nodes) == 1 and result.journals == []
    assert all(
        v.state == "UNAVAILABLE" and v.value is None for v in result.nodes[0].metrics.values()
    )
    with pytest.raises(ValueError):
        MetricValue(state="UNAVAILABLE", value="0")


@pytest.mark.parametrize(
    "failure",
    [
        "company",
        "snapshot",
        "invocation",
        "receipt",
        "scope",
        "overlap",
        "status",
        "duplicate_journal",
        "duplicate_line",
        "dimensions",
        "account_version",
        "unknown_coordinate",
        "net",
        "total",
        "float",
        "missing_account",
        "negative",
        "duplicate_account",
        "book_pin",
        "currency_pin",
        "period_pin",
        "ledger_pin",
    ],
)
def test_incompatible_or_incomplete_input_is_refused(metric_case, failure):
    request, receipt, projection = metric_case
    run(metric_case)
    if failure in ("company", "invocation"):
        request = request.model_copy(update={failure + "_id": uuid4()})
    elif failure == "snapshot":
        request = request.model_copy(update={"snapshot_at": request.snapshot_at.replace(year=2027)})
    elif failure == "receipt":
        request = request.model_copy(update={"expected_reconciliation_sha256": "0" * 64})
    elif failure == "scope":
        del receipt["selection"]["book_id"]
    elif failure == "overlap":
        receipt["missing_coordinates"] = ["Base!S2"]
    elif failure == "status":
        receipt["status"] = "UNAVAILABLE"
    elif failure == "duplicate_journal":
        receipt["accepted"].append(deepcopy(receipt["accepted"][0]))
    elif failure == "duplicate_line":
        receipt["accepted"][0]["lines"][1]["line"] = receipt["accepted"][0]["lines"][0]["line"]
    elif failure == "dimensions":
        receipt["accepted"][0]["lines"][0]["dimensions"]["state"] = "UNESTABLISHED"
    elif failure == "account_version":
        receipt["movement_trial_balance"][0]["account"]["version_id"] = str(uuid4())
    elif failure == "unknown_coordinate":
        receipt["movement_trial_balance"][0]["source_coordinates"] = ["Base!S288"]
    elif failure == "net":
        receipt["movement_trial_balance"][0]["net_movement"] = "999"
    elif failure == "total":
        receipt["journal_debit_total"] = "999"
    elif failure == "float":
        receipt["movement_trial_balance"][0]["debit"] = 731.97
    elif failure == "missing_account":
        receipt["movement_trial_balance"] = []
    elif failure == "negative":
        receipt["movement_trial_balance"][0].update(debit="-1", credit="0", net_movement="-1")
    elif failure.endswith("_pin"):
        receipt["selection"][failure.replace("_pin", "_id")]["version_id"] = str(uuid4())
    else:
        receipt["movement_trial_balance"].append(deepcopy(receipt["movement_trial_balance"][0]))
    with pytest.raises(WorkspaceError):
        run((request, receipt, projection))


def test_exact_result_pin_and_hostile_decimal_context(metric_case):
    result = run(metric_case)
    request = metric_case[0].model_copy(update={"expected_result_sha256": result.result_sha256})
    with localcontext() as caller:
        caller.prec = 2
        caller.Emax = 1
        caller.traps[Inexact] = True
        assert run((request, *metric_case[1:])) == result
    with pytest.raises(WorkspaceError, match="stale"):
        run((request.model_copy(update={"expected_result_sha256": "0" * 64}), *metric_case[1:]))


def test_read_producer_reuses_existing_reconciliation_scope(metric_case, monkeypatch):
    from finai_api.services import journal_reconciliation

    request, receipt, projection = metric_case
    expected = run(metric_case)

    def reconcile(principal, invocation, company, at):
        assert (invocation, company, at) == (
            request.invocation_id,
            request.company_id,
            request.snapshot_at,
        )
        return {"reconciliation": receipt, "source_projection": projection}

    monkeypatch.setattr(journal_reconciliation, "reconcile", reconcile)
    assert metrics.produce(SimpleNamespace(permissions=["ontology_read"]), request) == expected
