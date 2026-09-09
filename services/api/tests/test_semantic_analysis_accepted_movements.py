"""Retained values only: accepted movement worksheet guards and source/journal drill."""

from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from investigation_full_review_support import metric_graph, workspace_graph

from finai_api.services import accepted_movements_function, company_financial_metrics
from finai_api.services import semantic_analysis_accepted_movements as adapter
from finai_api.services.semantic_analysis_movements import build as source_build
from finai_api.services.semantic_analysis_support import digest
from finai_api.services.workspace import WorkspaceError


@pytest.fixture
def case():
    workspace = workspace_graph()
    source_history, source_plan, source_resolver, source_request = workspace
    request, receipt, projection = metric_graph(workspace)
    receipt["receipt_hash"] = digest(receipt)
    result = company_financial_metrics.compute(request, receipt, projection)
    descriptor, rows, contributors = source_build(
        source_history, source_plan, source_resolver, source_request.company_id
    )
    refs = [
        result.nodes[0].subject.model_dump(mode="json"),
        result.binding.model_dump(mode="json"),
        result.source_function.model_dump(mode="json"),
    ]
    currency = source_resolver.version(result.selection["currency_id"].model_dump(mode="json"))
    refs.append({k: currency[k] for k in ("resource_id", "version_id", "content_hash")})
    journals = {}
    for entry in result.journals:
        ref = {**entry.journal.model_dump(mode="json"), "content_hash": "a" * 64}
        refs.append(ref)
        journals[ref["resource_id"]] = ref
        for kind, pins in (
            ("JournalLine", entry.lines),
            ("AccountDimensionPolicy", entry.dimension_policies),
        ):
            for child in pins:
                journals[str(child.resource_id)] = {
                    **child.model_dump(mode="json"),
                    "content_hash": "e" * 64,
                    "object_type": kind,
                    "display_name": "Reviewed " + kind,
                }
    function = {"resource_id": str(uuid4()), "version_id": str(uuid4()), "content_hash": "b" * 64}
    frozen = {
        "company_id": str(request.company_id),
        "source_invocation_id": str(request.invocation_id),
        "source_invocation_receipt_hash": source_history["receipt_hash"],
        "result_sha256": result.result_sha256,
        "reconciliation_receipt_hash": result.reconciliation_receipt_hash,
        "source_receipt_hash": result.source_receipt_hash,
        "source_valid_at": descriptor.valid_at,
        "source_known_at": descriptor.known_at,
        "journal_observed_at": result.snapshot_at.isoformat(),
        "selection": {k: v.model_dump(mode="json") for k, v in result.selection.items()},
        "binding": result.binding.model_dump(mode="json"),
        "source_function": result.source_function.model_dump(mode="json"),
        "contributors": refs,
    }
    output = {
        "contract": "function-result/1",
        "implementation": {"implementation_id": adapter.IMPLEMENTATION},
        "accepted_movements": deepcopy(frozen),
        "financial_metrics": result.model_dump(mode="json"),
        "current_use_authorized": False,
        "business_effect_authorized": False,
        "journal_observed_at": frozen["journal_observed_at"],
        "query": {"valid_at": descriptor.valid_at, "known_at": descriptor.known_at},
        "run_id": "fcr_" + "c" * 64,
        "metric_outputs": accepted_movements_function.metric_outputs(
            result,
            SimpleNamespace(
                valid_at=datetime.fromisoformat(descriptor.valid_at),
                known_at=datetime.fromisoformat(descriptor.known_at),
            ),
            refs,
        ),
    }
    history = {
        "invocation_id": str(uuid4()),
        "receipt_hash": "d" * 64,
        "receipt": {"recorded_at": "2026-09-08T04:00:00Z"},
        "output": output,
    }
    plan = {"function": function, "accepted_movements": frozen}

    def version(ref):
        if ref["resource_id"] == function["resource_id"]:
            return function
        return journals.get(ref["resource_id"]) or source_resolver.version(ref)

    return (
        history,
        plan,
        SimpleNamespace(
            version=version,
            principal=object(),
            source_history=source_history,
            source_plan=source_plan,
            source_resolver=source_resolver,
        ),
        request.company_id,
        descriptor,
        rows,
        contributors,
    )


def test_retained_account_values_only_with_original_and_journal_evidence(case):
    before = deepcopy((case[0], case[1]))
    descriptor, rows, contributors = adapter.project_retained(*case)
    original = case[0]["output"]["financial_metrics"]
    assert len(rows) == len(original["nodes"]) - 1 == 2
    assert descriptor.contract == "semantic-analysis/2" and descriptor.measure is None
    assert descriptor.visual == "NONE" and all(f.aggregation == "NONE" for f in descriptor.fields)
    for row, node in zip(rows, original["nodes"][1:], strict=True):
        assert {key: row.values[key].value for key in node["metrics"]} == {
            key: v["value"] for key, v in node["metrics"].items()
        }
        assert {c.basis for c in contributors[row.key]} == {
            "ORIGINAL_SOURCE",
            "CANONICAL_DEFINITION",
        }
    assert descriptor.recorded_at == case[0]["receipt"]["recorded_at"]
    assert any(c.label == "Journal observed at" for c in descriptor.context)
    assert not descriptor.current_use_authorized
    assert (case[0], case[1]) == before


def test_typed_evidence_references_preserve_exact_versions_and_source_cells(case):
    _, _, contributors = adapter.project_retained(*case)
    for group in contributors.values():
        source, journal = group
        assert all("reference" not in c.model_dump(mode="json") for c in source.cells)
        assert journal.cells[0].value == "Base!S2"
        assert "reference" not in journal.cells[0].model_dump(mode="json")
        for cell in journal.cells[1:]:
            assert cell.reference is not None
            node = case[2].version(cell.reference.model_dump(mode="json"))
            assert cell.value == node["display_name"]
            assert cell.reference.content_hash == node["content_hash"]
            assert cell.model_dump(mode="json")["reference"] == {
                k: node[k] for k in ("resource_id", "version_id", "content_hash")
            }
            assert "@" not in cell.value


def test_absent_reference_preserves_existing_nested_evidence_serialization():
    from finai_api.domain.semantic_analysis import Contributor

    old = {
        "label": "Business evidence",
        "reference": {
            "resource_id": str(uuid4()),
            "version_id": str(uuid4()),
            "content_hash": "f" * 64,
        },
        "cells": [
            {"label": "Business value", "value": "731.97", "coordinate": None, "formula": None}
        ],
        "document_id": None,
        "source_sha256": None,
        "sheet": None,
        "coordinate": None,
        "basis": "CANONICAL_DEFINITION",
    }
    restored = Contributor.model_validate(old)
    assert restored.model_dump(mode="json") == old
    assert digest(restored.model_dump(mode="json")) == digest(old)


@pytest.mark.parametrize("change", ["resource_id", "version_id", "object_type"])
def test_reference_cell_refuses_wrong_retained_resource(case, change):
    journal = case[0]["output"]["financial_metrics"]["journals"][0]
    node = case[2].version(journal["lines"][0])
    node[change] = str(uuid4()) if change != "object_type" else "LocalAccount"
    with pytest.raises(WorkspaceError) as error:
        adapter.project_retained(*case)
    assert error.value.status == 409


@pytest.mark.parametrize(
    "change",
    [
        "amount",
        "company",
        "source_time",
        "journal_time",
        "currency",
        "source_receipt",
        "journal_pin",
        "account_pin",
        "metric_output",
    ],
)
def test_exact_retained_contract_mismatches_are_refused(case, change):
    history, plan, resolver, company, descriptor, rows, contributors = case
    if change == "amount":
        history["output"]["financial_metrics"]["nodes"][1]["metrics"]["debit_movement"]["value"] = (
            "999"
        )
    elif change == "company":
        company = uuid4()
    elif change == "source_time":
        descriptor = descriptor.model_copy(update={"known_at": "2030-01-01T00:00:00Z"})
    elif change == "journal_time":
        history["output"]["journal_observed_at"] = "2030-01-01T00:00:00Z"
    elif change == "currency":
        plan["accepted_movements"]["selection"]["currency_id"]["version_id"] = str(uuid4())
    elif change == "source_receipt":
        descriptor = descriptor.model_copy(update={"receipt_hash": "e" * 64})
    elif change == "journal_pin":
        plan["accepted_movements"]["contributors"][-1]["version_id"] = str(uuid4())
    elif change == "account_pin":
        rows[0] = rows[0].model_copy(
            update={"trace": rows[0].trace.model_copy(update={"version_id": uuid4()})}
        )
    else:
        history["output"]["metric_outputs"][0]["value"] = "999"
    with pytest.raises(WorkspaceError):
        adapter.project_retained(history, plan, resolver, company, descriptor, rows, contributors)


def test_full_build_reopens_exact_source_without_financial_reexecution(case, monkeypatch):
    from finai_api.services import journal_reconciliation, semantic_analysis

    history, plan, resolver, company, *_ = case

    def retained_source(principal, invocation_id):
        assert principal is resolver.principal
        assert str(invocation_id) == plan["accepted_movements"]["source_invocation_id"]
        return resolver.source_history, resolver.source_plan, resolver.source_resolver

    def no_reexecution(*args, **kwargs):
        raise AssertionError("Reopening must not recalculate accepted journal totals")

    monkeypatch.setattr(semantic_analysis, "load", retained_source)
    monkeypatch.setattr(company_financial_metrics, "produce", no_reexecution)
    monkeypatch.setattr(journal_reconciliation, "reconcile", no_reexecution)
    descriptor, rows, contributors = adapter.build(history, plan, resolver, company)
    assert len(rows) == 2 and len(contributors) == 2
    assert descriptor.invocation_id == UUID(history["invocation_id"])
