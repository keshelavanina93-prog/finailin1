"""Synthetic source dimensions, account observations, and quarantined reference calculations."""

from contextlib import contextmanager
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
from html import escape
from io import BytesIO
from types import SimpleNamespace
from uuid import UUID, uuid4, uuid5
from zipfile import ZipFile

import pytest
import xlrd
from test_source_contract_edges import journal_cells, workbook

from finai_api.domain.ontology_catalog import canonical_id
from finai_api.services import account_ontology, object_sets, petroleum_reporting, resources
from finai_api.services import source_dimensions as dimensions
from finai_api.services.workspace import WorkspaceError


def xlsx(sheets):
    target = BytesIO()
    with ZipFile(target, "w") as archive:
        sheet_refs = "".join(
            f'<sheet name="{escape(name)}" sheetId="{i}" r:id="r{i}"/>'
            for i, name in enumerate(sheets, 1)
        )
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
            + sheet_refs
            + "</sheets></workbook>",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(
                f'<Relationship Id="r{i}" Target="worksheets/sheet{i}.xml"/>'
                for i in range(1, len(sheets) + 1)
            )
            + "</Relationships>",
        )
        for i, cells in enumerate(sheets.values(), 1):
            rows = {}
            for address, cell in cells.items():
                row = int("".join(c for c in address if c.isdigit()))
                rows.setdefault(row, []).append(cell)
            data = "".join(
                f'<row r="{row}">' + "".join(values) + "</row>"
                for row, values in sorted(rows.items())
            )
            archive.writestr(
                f"xl/worksheets/sheet{i}.xml",
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                "<sheetData>" + data + "</sheetData></worksheet>",
            )
    return target.getvalue()


def text(address, value):
    return f'<c r="{address}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'


def number(address, value, formula=None, *, attrs="", kind="n"):
    f = "" if formula is None else f"<f{attrs}>{escape(formula)}</f>"
    return f'<c r="{address}" t="{kind}">{f}<v>{escape(str(value))}</v></c>'


@pytest.fixture
def dimension_source(monkeypatch):
    company, tenant, observation, version = [uuid4() for _ in range(4)]
    principal = SimpleNamespace(
        scope=SimpleNamespace(tenant_id=tenant, legal_entity_id="synthetic")
    )
    source = workbook(
        {
            **journal_cells(),
            (1, 24): "Region",
            (1, 25): "Budget Article New",
            (1, 26): "Department",
            (2, 24): "Region A",
            (2, 25): "",
            (2, 26): "Department A",
        }
    )
    digest = sha256(source).hexdigest()
    evidence = canonical_id(tenant, "SourceEvidence", digest)
    page = {
        "source_sha256": digest,
        "total_rows": 11,
        "rows": [
            {
                "resource_id": str(observation),
                "published_version_id": str(version),
                "publication_state": "APPROVED",
                "attributes": {
                    "legal_entity_id": str(company),
                    "evidence_id": str(evidence),
                    "source_row_key": "Synthetic!3",
                    "source_details": {
                        "cells": {
                            "Y": {"type": xlrd.XL_CELL_TEXT, "value": "Region A"},
                            "Z": {"type": xlrd.XL_CELL_EMPTY, "value": ""},
                            "AA": {"type": xlrd.XL_CELL_TEXT, "value": "Department A"},
                        }
                    },
                },
            }
        ],
    }
    nodes = {}
    monkeypatch.setattr(dimensions, "prepare", lambda *_: deepcopy(page))
    monkeypatch.setattr(
        dimensions, "document_bytes", lambda *_: ({"source_sha256": digest}, source)
    )
    monkeypatch.setattr(
        resources,
        "current_resources",
        lambda _p, ids: {str(i): deepcopy(nodes[str(i)]) for i in ids if str(i) in nodes},
    )
    monkeypatch.setattr(resources, "propose", lambda _p, proposal: proposal)
    return principal, company, page, nodes


def test_dimension_proposal_preserves_cells_missingness_and_exact_observation_pins(
    dimension_source,
):
    principal, company, page, nodes = dimension_source
    result = dimensions.inspect(principal, "doc", "Synthetic", company, 0)
    assert result["source_rows"] == 1 and result["next_offset"] == 10
    assert result["assignments"][1] == {
        "source_row": "Synthetic!3",
        "dimension": "Budget Article New",
        "value": None,
        "state": "MISSING",
    }
    proposal = dimensions.propose(principal, "doc", "Synthetic", company, 0)
    assert proposal.access_entity == "synthetic"
    for mutation in proposal.mutations:
        nodes[str(mutation.resource_id)] = {
            "object_type": mutation.object_type,
            "attributes": deepcopy(mutation.attributes),
            "evidence_class": "SOURCE_BOUND",
            "authority_state": "APPROVED",
            "version_id": str(uuid4()),
        }
    observation = page["rows"][0]
    nodes[observation["resource_id"]] = {
        "evidence_class": "SOURCE_BOUND",
        "attributes": observation["attributes"],
    }
    assignments = [m for m in proposal.mutations if m.object_type == "SourceDimensionAssignment"]
    assert len(assignments) == 2
    for item in assignments:
        assert proposal.source_versions[item.resource_id] == {
            UUID(observation["resource_id"]): UUID(observation["published_version_id"])
        }
        dimensions.validate_assignment(item, lambda key, *_: nodes[key])
    coordinates = {
        m.attributes["coordinate"] for m in proposal.mutations if m.object_type == "SourceRecord"
    }
    assert coordinates == {
        "Synthetic!Y2",
        "Synthetic!Z2",
        "Synthetic!AA2",
        "Synthetic!Y3",
        "Synthetic!AA3",
    }
    replay = dimensions.inspect(principal, "doc", "Synthetic", company, 0)
    assert replay["new_resources"] == 0
    assert {a["state"] for a in replay["assignments"]} == {"APPROVED", "MISSING"}
    with pytest.raises(WorkspaceError, match="already published"):
        dimensions.propose(principal, "doc", "Synthetic", company, 0)
    nodes[str(assignments[0].resource_id)]["attributes"]["member_id"] = str(uuid4())
    with pytest.raises(WorkspaceError, match="review a new version"):
        dimensions.inspect(principal, "doc", "Synthetic", company, 0)


@pytest.mark.parametrize(
    "case,message",
    [
        ("unpublished", "Publish the exact"),
        ("number", "explicit text"),
        ("header", "headers differ"),
    ],
)
def test_dimension_discovery_refuses_unreviewed_or_ambiguous_inputs(
    dimension_source, monkeypatch, case, message
):
    principal, company, page, _ = dimension_source
    if case == "unpublished":
        page["rows"][0]["publication_state"] = "UNPUBLISHED"
    if case == "number":
        page["rows"][0]["attributes"]["source_details"]["cells"]["Y"] = {
            "type": xlrd.XL_CELL_NUMBER,
            "value": "123",
        }
    if case == "header":
        raw = workbook(
            {(1, 24): "Different header", (1, 25): "Budget Article New", (1, 26): "Department"}
        )
        monkeypatch.setattr(
            dimensions,
            "document_bytes",
            lambda *_: ({"source_sha256": sha256(raw).hexdigest()}, raw),
        )
    with pytest.raises(WorkspaceError, match=message):
        dimensions.inspect(principal, "doc", "Synthetic", company, 0)


def test_member_drill_is_company_and_source_scoped_and_does_not_sum_assignments(
    dimension_source, monkeypatch
):
    principal, company, page, nodes = dimension_source
    member = uuid4()
    with pytest.raises(WorkspaceError, match="belonging to this source company"):
        dimensions.movements(principal, "doc", "Synthetic", company, member, 0)
    nodes[str(member)] = {
        "object_type": "DimensionMember",
        "attributes": {"dimension_id": str(uuid5(company, "source-dimension:Region"))},
    }
    monkeypatch.setattr(object_sets, "query_objects", lambda _p, query: query)
    query = dimensions.movements(principal, "doc", "Synthetic", company, member, 5)
    assert query.object_type == "SourceDimensionAssignment"
    assert query.traversal[0].name == "observation_id" and query.offset == 5
    assert {f.field: f.value for f in query.filters} == {
        "member_id": str(member),
        "evidence_id": str(
            canonical_id(principal.scope.tenant_id, "SourceEvidence", page["source_sha256"])
        ),
    }
    nodes[str(member)]["attributes"]["dimension_id"] = str(uuid4())
    with pytest.raises(WorkspaceError, match="belonging"):
        dimensions.movements(principal, "doc", "Synthetic", company, member, 0)


def account_cells():
    return {
        a: text(a, v)
        for a, v in {
            "B1": "Код",
            "C1": "Наименование",
            "D1": "Субконто 1",
            "B2": "0012.10",
            "C2": "SYNTHETIC account",
            "D2": "Region",
        }.items()
    }


@pytest.fixture
def account_source(monkeypatch):
    principal = SimpleNamespace(
        scope=SimpleNamespace(tenant_id=uuid4(), legal_entity_id="synthetic")
    )
    state = {"content": xlsx({"Accounts": account_cells()}), "published": [], "evidence": None}
    monkeypatch.setattr(account_ontology, "source_bytes", lambda *_: state["content"])

    @contextmanager
    def connection(*_):
        yield SimpleNamespace(
            execute=lambda *_: SimpleNamespace(fetchall=lambda: [(i,) for i in state["published"]])
        )

    def evidence(*_):
        if state["evidence"] is None:
            raise WorkspaceError(404, "Not retained")
        return state["evidence"]

    monkeypatch.setattr(resources, "resource_connection", connection)
    monkeypatch.setattr(resources, "_get", evidence)
    monkeypatch.setattr(resources, "propose", lambda _p, proposal: proposal)
    return principal, state


def test_observed_account_proposal_never_infers_company_or_reporting_mapping(account_source):
    principal, state = account_source
    proposal = account_ontology.propose_accounts(principal, "receipt", 0, 10)
    items = {m.object_type: m for m in proposal.mutations}
    assert set(items) == {"SourceEvidence", "SourceRecord", "SourceAccountDefinition"}
    assert items["SourceRecord"].attributes["coordinate"] == "Accounts!B2"
    account = items["SourceAccountDefinition"]
    assert account.attributes["account_code"] == "0012.10"
    assert account.attributes["definition"]["financial_mapping"] == "UNESTABLISHED"
    assert account.attributes["definition"]["required_dimension_policy"] == "UNESTABLISHED"
    assert account.attributes["definition"]["analytics"][0]["coordinate"] == "Accounts!D2"
    assert all(m.evidence_class == "SOURCE_BOUND" for m in proposal.mutations)
    state["published"] = [account.resource_id]
    state["evidence"] = {"attributes": {"sha256": sha256(state["content"]).hexdigest()}}
    with pytest.raises(WorkspaceError, match="already published"):
        account_ontology.propose_accounts(principal, "receipt", 0, 10)
    state["evidence"]["attributes"]["sha256"] = "a" * 64
    with pytest.raises(WorkspaceError, match="incompatible content"):
        account_ontology.propose_accounts(principal, "receipt", 0, 10)


@pytest.mark.parametrize(
    "case,message",
    [
        ("unrecognized", "recognized account"),
        ("range", "requested range"),
        ("duplicate", "unresolved source"),
        ("formula", "unresolved source"),
        ("missing-name", "unresolved source"),
    ],
)
def test_account_discovery_requires_resolved_literal_definition(account_source, case, message):
    principal, state = account_source
    cells = account_cells()
    if case == "unrecognized":
        cells["B1"] = text("B1", "Unknown")
    if case == "duplicate":
        cells.update({"B3": text("B3", "0012.10"), "C3": text("C3", "Duplicate")})
    if case == "formula":
        cells["B2"] = number("B2", "0012.10", '"0012.10"')
    if case == "missing-name":
        cells.pop("C2")
    state["content"] = xlsx({"Accounts": cells})
    with pytest.raises(WorkspaceError, match=message):
        account_ontology.propose_accounts(principal, "receipt", 99 if case == "range" else 0, 10)


def reference_sheets():
    return {
        "Revenue Breakdown": {
            "A1": text("A1", "Product"),
            "D1": text("D1", "Net Revenue"),
            "A2": text("A2", "Euro Regular, L"),
            "B2": number("B2", "100.1"),
            "C2": number("C2", "0.1"),
            "D2": number("D2", "999", "B2-C2", attrs=' t="shared" si="0" ref="D2:D3"'),
            "A3": text("A3", "Diesel, L"),
            "B3": number("B3", "20"),
            "C3": number("C3", "2"),
            "D3": number("D3", "888", "", attrs=' t="shared" si="0"'),
            "A4": text("A4", "Kerosene, L"),
            "B4": number("B4", "7"),
            "C4": number("C4", "1"),
            "D4": number("D4", "6", "B4-C4"),
            "A5": text("A5", "Total"),
            "A6": text("A6", " "),
            "D36": number("D36", "130"),
        },
        "COGS Breakdown": {
            "K1": number("K1", "6"),
            "L1": number("L1", "7310"),
            "O1": number("O1", "8230"),
            "A2": text("A2", "Euro Regular (Wholesale)"),
            "K2": number("K2", "40"),
            "L2": number("L2", "1"),
            "O2": number("O2", "2"),
            "A3": text("A3", "Diesel"),
            "K3": number("K3", "5"),
            "O3": number("O3", "1"),
            "A4": text("A4", "Unknown source product"),
            "K4": number("K4", "2"),
            "A5": text("A5", "Итого"),
        },
        "Budget (2)": {"B2": number("B2", "120"), "B17": number("B17", "50")},
    }


def test_quarantined_reference_reconstructs_formulas_and_reports_cached_disagreement():
    raw = xlsx(reference_sheets())
    result = petroleum_reporting.reconstruct(raw)
    assert result == petroleum_reporting.reconstruct(raw)
    metrics = {m["id"]: m for m in result["metrics"]}
    assert (
        result["state"] == "REFERENCE_ONLY" and result["source_sha256"] == sha256(raw).hexdigest()
    )
    assert Decimal(metrics["revenue.total"]["amount"]) == Decimal("118")
    assert Decimal(metrics["gross_profit"]["amount"]) == Decimal("73")
    assert metrics["ga"]["amount"] is None and metrics["legacy_ebitda"]["amount"] is None
    differences = {c["coordinate"]: Decimal(c["difference"]) for c in result["comparisons"]}
    assert differences == {
        "Budget (2)!B2": Decimal("-2"),
        "Budget (2)!B17": Decimal("-1"),
        "Revenue Breakdown!D36": Decimal("-6"),
    }
    diesel = next(f for f in result["facts"] if f["metric"] == "revenue.retail.diesel")
    assert diesel["amount"] == "18" and diesel["coordinates"] == [
        "Revenue Breakdown!B3",
        "Revenue Breakdown!C3",
    ]
    assert all(f["mapping_state"] == "PROPOSED" for f in result["facts"])
    assert not any(f["source_row"] == 5 for f in result["facts"])
    assert result["missing_requirements"] and not result["findings"]


@pytest.mark.parametrize(
    "case", ["formula", "shared-anchor", "error", "nan", "large", "comparison"]
)
def test_reference_errors_block_dependent_metrics_without_promoting_cache(case):
    sheets = reference_sheets()
    if case == "formula":
        sheets["Revenue Breakdown"]["D2"] = number("D2", "999", "B2+C2")
    if case == "shared-anchor":
        sheets["Revenue Breakdown"]["D3"] = number("D3", "888", "", attrs=' t="shared" si="99"')
    if case == "error":
        sheets["Revenue Breakdown"]["B2"] = number("B2", "#N/A", kind="e")
    if case == "nan":
        sheets["Revenue Breakdown"]["B2"] = number("B2", "NaN")
    if case == "large":
        sheets["Revenue Breakdown"]["B2"] = number("B2", "1e24")
    if case == "comparison":
        sheets["Budget (2)"]["B17"] = number("B17", "bad")
    result = petroleum_reporting.reconstruct(xlsx(sheets))
    metrics = {m["id"]: m for m in result["metrics"]}
    assert result["state"] == "REFERENCE_ONLY"
    assert metrics["legacy_ebitda"]["amount"] is None
    if case == "comparison":
        assert result["findings"] == [
            {"code": "COMPARISON_UNAVAILABLE", "message": "Budget (2)!B17"}
        ]
    else:
        assert metrics["revenue.total"]["amount"] is None
        assert metrics["gross_profit"]["state"] == "UNAVAILABLE"
        assert all(f["code"] == "SOURCE_AMOUNT_UNAVAILABLE" for f in result["findings"])


@pytest.mark.parametrize("case", ["missing-sheet", "revenue-header", "cogs-header"])
def test_reference_contract_requires_explicit_source_layout(case):
    sheets = reference_sheets()
    if case == "missing-sheet":
        sheets.pop("COGS Breakdown")
    if case == "revenue-header":
        sheets["Revenue Breakdown"]["A1"] = text("A1", "Other")
    if case == "cogs-header":
        sheets["COGS Breakdown"]["K1"] = number("K1", "7")
    with pytest.raises(ValueError, match=r"requires|Unsupported"):
        petroleum_reporting.reconstruct(xlsx(sheets))
