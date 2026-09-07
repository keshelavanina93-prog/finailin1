"""Workspace intent gates over a synthetic retained posted result, with no new execution."""

from contextlib import nullcontext
from copy import deepcopy
from uuid import NAMESPACE_DNS, uuid5

import pytest
from pydantic import ValidationError
from test_seg_expense_source import workbook

from finai_api.domain.semantic_analysis import ProjectionRequest
from finai_api.services import semantic_analysis as service
from finai_api.services.posted_movements_function import calculate
from finai_api.services.seg_expense_source import read_base
from finai_api.services.semantic_analysis_support import digest, pin
from finai_api.services.workspace import WorkspaceError


def uid(name):
    return uuid5(NAMESPACE_DNS, "semantic-test:" + name)


@pytest.fixture
def case(monkeypatch):
    records = {}

    def record(name, kind, attributes=None):
        row = dict(
            resource_id=str(uid(name)),
            version_id=str(uid(name + ":version")),
            content_hash=digest(name),
            display_name=name,
            object_type=kind,
            authority_state="APPROVED",
            attributes=attributes or {},
        )
        records[row["resource_id"]] = row
        return row

    company = record("Company", "LegalEntity")
    currency = record("GEL", "Currency", {"code": "GEL"})
    context = {
        "currency_id": currency["resource_id"],
        "functional_currency_id": currency["resource_id"],
        "amount_field": "source_amount",
        "amount_semantics": "DEBIT_CREDIT",
        "vat_treatment": "AS_POSTED",
    }
    for name, kind in (
        ("ledger", "Ledger"),
        ("book", "AccountingBook"),
        ("period", "FiscalPeriod"),
    ):
        context[name + "_id"] = record(name, kind)["resource_id"]
    scope = record("scope", "SourceAccountingScope", {"legal_entity_id": company["resource_id"]})
    binding = record("binding", "SourceAccountingBinding", context)
    function = record("Function", "FunctionDefinition")
    parsed = read_base(workbook())
    evidence = record("evidence", "SourceEvidence", {"sha256": parsed["source_sha256"]})
    accounts = {}
    for code in ("0012.01", "3110"):
        row = record(code, "LocalAccount")
        accounts[code] = {key: row[key] for key in ("resource_id", "version_id")}
    source = dict(
        sha256=parsed["source_sha256"],
        sheet="Base",
        row_count=1,
        context=context,
        observed_from="2025-01-01",
        observed_through="2025-01-31",
        accounts=accounts,
        company_id=company["resource_id"],
        document_id="ir_" + "a" * 64,
        binding=pin(binding).model_dump(mode="json"),
        scope=pin(scope).model_dump(mode="json"),
        evidence=pin(evidence).model_dump(mode="json"),
    )
    implementation = {"implementation_id": "accounting.retained-posted-movements/v1"}
    output = dict(
        source_document=source,
        source_rows=parsed["rows"],
        posted_movements=calculate(parsed, source),
        run_id="fcr_" + "b" * 64,
        authority="GUARDED_POSTED_MOVEMENT_ANALYSIS",
        coverage="RETAINED_SOURCE_POSTINGS_WITH_EXPLICIT_EXCLUSIONS",
        query={"valid_at": "2026-09-07T00:00:00Z", "known_at": "2026-09-07T00:00:00Z"},
    )
    history = dict(
        invocation_id=str(uid("invocation")),
        receipt_hash="c" * 64,
        output=output,
        receipt={"recorded_at": "2026-09-07T00:00:01Z"},
    )
    plan = dict(
        source_document=deepcopy(source),
        implementation=implementation,
        function=pin(function).model_dump(mode="json"),
    )

    class Resolver:
        def read_session(self):
            return nullcontext(self)

        def version(self, ref):
            return records[str(ref["resource_id"])]

        def field(self, row, field):
            return records[row["attributes"][field]]

    monkeypatch.setattr(service, "require_permission", lambda *_: None)
    monkeypatch.setattr(service, "load", lambda *_: (history, plan, Resolver()))
    request = ProjectionRequest(invocation_id=uid("invocation"), company_id=uid("Company"))
    return request, history, plan


def test_same_value_and_original_cells_with_selection_and_non_aggregating_grouping(case):
    request, history, _ = case
    original = deepcopy(history)
    first = service.project(None, request)
    assert len(first.rows) == 2
    assert [r.values["posted_amount"].value for r in first.rows] == ["731.97", "731.97"]
    assert first.descriptor.partition_keys == ["side"]
    selected = service.project(
        None,
        ProjectionRequest(
            **request.model_dump(exclude_defaults=True),
            descriptor_sha256=first.descriptor_sha256,
            filters=[{"field": "side", "value": "debit"}],
            group_by="side",
            selected_row=first.rows[0].key,
        ),
    )
    assert len(selected.rows) == 1 and selected.total_rows == 2
    assert selected.sections[0].row_keys == [first.rows[0].key]
    assert selected.selection.contributor.coordinate == "Base!S2"
    assert (
        next(c for c in selected.selection.contributor.cells if c.coordinate == "Base!S2").value
        == "731.97"
    )
    assert selected.descriptor_sha256 == first.descriptor_sha256
    assert history == original


@pytest.mark.parametrize(
    "change,status",
    [
        ({"company_id": uid("other")}, 404),
        ({"descriptor_sha256": "0" * 64}, 409),
        ({"filters": [{"field": "posted_amount", "value": "731.97"}]}, 422),
        ({"filters": [{"field": "side", "value": "invented"}]}, 422),
        ({"filters": [{"field": "side", "value": True}]}, 422),
        ({"group_by": "currency_or_join"}, 422),
        ({"selected_row": "row_" + "0" * 64}, 422),
    ],
)
def test_refuses_cross_company_revision_and_illegal_operations(case, change, status):
    request, _, _ = case
    first = service.project(None, request)
    payload = {**request.model_dump(), "descriptor_sha256": first.descriptor_sha256, **change}
    with pytest.raises(WorkspaceError) as refused:
        service.project(None, ProjectionRequest.model_validate(payload))
    assert refused.value.status == status


def test_filters_cannot_leave_an_incompatible_selection(case):
    request, _, _ = case
    first = service.project(None, request)
    with pytest.raises(WorkspaceError, match="outside"):
        service.project(
            None,
            ProjectionRequest(
                **request.model_dump(exclude_defaults=True),
                descriptor_sha256=first.descriptor_sha256,
                filters=[{"field": "side", "value": "credit"}],
                selected_row=first.rows[0].key,
            ),
        )


@pytest.mark.parametrize(
    "extra",
    [
        {"aggregation": "sum"},
        {"expression": "javascript:alert(1)"},
        {"filters": [{"field": "side", "value": "debit"}]},
        {"contributor_index": 1},
    ],
)
def test_unpinned_or_executable_intents_are_not_a_wire_contract(case, extra):
    request, _, _ = case
    with pytest.raises(ValidationError):
        ProjectionRequest.model_validate({**request.model_dump(), **extra})


@pytest.mark.parametrize("change", ["currency", "contributors", "amount", "coverage"])
def test_retained_posting_contract_refuses_inconsistent_evidence(case, change):
    request, history, _ = case
    output = history["output"]
    group = output["posted_movements"]["groups"][0]
    if change == "currency":
        group["currency_id"] = str(uid("other-currency"))
    elif change == "contributors":
        group["source_coordinates"] *= 2
    elif change == "amount":
        group["value"] = "NaN"
    else:
        output["posted_movements"]["coverage"]["included_rows"] = 10
    with pytest.raises(WorkspaceError):
        service.project(None, request)
