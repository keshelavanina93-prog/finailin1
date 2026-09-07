"""Synthetic retained-byte contract tests; no authentic later-source acceptance."""

from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace
from uuid import UUID, uuid4, uuid5
from zipfile import ZipFile

import pytest
from test_seg_expense_source import HEADERS, workbook
from test_source_accounting_context import context

from finai_api.domain.ontology_catalog import canonical_id
from finai_api.services import accounting_source_document, source_company_alias, source_snapshot
from finai_api.services.seg_expense_source import read_base
from finai_api.services.workspace import WorkspaceError


def setup(monkeypatch, content=None):
    content = content or workbook()
    parsed = read_base(content)
    item, nodes, ids = context()
    principal = SimpleNamespace(scope=SimpleNamespace(tenant_id="snapshot-test"))
    evidence = canonical_id(
        principal.scope.tenant_id, "SourceEvidence", sha256(content).hexdigest()
    )
    company = UUID(ids["company"])
    chart = uuid5(company, "1c-observed-chart")
    scope = uuid5(evidence, f"accounting-scope:{company}:Base:seg_expense_base")
    coordinate = "Base!rows:2:2"
    record = uuid5(evidence, coordinate)
    ids.update(evidence=str(evidence), chart=str(chart), scope=str(scope), record=str(record))
    attrs = deepcopy(item.attributes)
    attrs.update(
        scope_id=str(scope),
        amount_field="source_amount",
        amount_semantics="DEBIT_CREDIT",
        vat_treatment="AS_POSTED",
        supplementary_amount_field="annotated_amount",
        supplementary_amount_role="NON_AUTHORITATIVE_SOURCE_OBSERVATION",
    )
    nodes[ids["scope"]] = {
        "object_type": "SourceAccountingScope",
        "evidence_class": "SOURCE_BOUND",
        "attributes": {
            "document_id": "ir_synthetic",
            "legal_entity_id": str(company),
            "chart_id": str(chart),
            "worksheet": "Base",
            "source_profile": "seg_expense_base",
            "observed_from": parsed["observed_from"],
            "observed_through": parsed["observed_through"],
            "date_basis": "OBSERVED_MOVEMENT_DATE_EXTENT",
            "coverage_state": "UNESTABLISHED",
            "evidence_id": str(evidence),
            "source_record_id": str(record),
        },
    }
    for key, kind, values in [
        ("company", "LegalEntity", {"evidence_id": str(evidence)}),
        ("chart", "LocalChartOfAccounts", {"legal_entity_id": str(company)}),
        ("evidence", "SourceEvidence", {"sha256": sha256(content).hexdigest()}),
        ("record", "SourceRecord", {"evidence_id": str(evidence), "coordinate": coordinate}),
    ]:
        nodes[ids[key]] = {
            "object_type": kind,
            "attributes": values,
            "evidence_class": "SOURCE_BOUND",
        }
    nodes[ids["company"]]["display_name"] = parsed["company_label"]
    for key, kind in [("ledger", "Ledger"), ("book", "AccountingBook"), ("period", "FiscalPeriod")]:
        nodes[ids[key]]["object_type"] = kind
    nodes[ids["ledger"]]["attributes"]["chart_id"] = str(chart)
    nodes[ids["period"]]["attributes"].update(starts_on="2025-01-01", ends_on="2025-01-31")
    accounts = {}
    for code in ("0012.01", "3110"):
        identity = str(uuid5(chart, code))
        version = str(uuid4())
        nodes[identity] = {
            "object_type": "LocalAccount",
            "evidence_class": "USER_ASSERTED",
            "attributes": {"chart_id": str(chart), "account_code": code},
            "version_id": version,
        }
        accounts[code] = {"resource_id": identity, "version_id": version}
    nodes[ids["mapping"]]["attributes"]["definition"] = {
        "kind": "EXACT_SOURCE_ACCOUNT_IDENTITIES",
        "version": 1,
        "company_id": str(company),
        "chart_id": str(chart),
        "accounts": accounts,
    }
    dimensions = str(uuid4())
    nodes[dimensions] = {
        "object_type": "MappingVersion",
        "evidence_class": "USER_ASSERTED",
        "attributes": {
            "definition": {
                "kind": "PRESERVE_SOURCE_DIMENSION_COORDINATES",
                "company_id": str(company),
                "aggregation_dimensions": [],
            },
        },
    }
    attrs["dimension_mapping_id"] = dimensions
    binding = str(uuid5(scope, "accounting-binding"))
    nodes[binding] = {
        "object_type": "SourceAccountingBinding",
        "evidence_class": "USER_ASSERTED",
        "attributes": attrs,
    }
    for identity, row in nodes.items():
        row.update(resource_id=identity, content_hash="a" * 64, authority_state="APPROVED")
        row.setdefault("version_id", str(uuid4()))
    metadata = {"source_sha256": sha256(content).hexdigest(), "filename": "synthetic.xlsx"}

    def reader(*_):
        return metadata, content

    monkeypatch.setattr(source_snapshot, "read_source", reader)
    monkeypatch.setattr(accounting_source_document, "read_source", reader)
    monkeypatch.setattr(source_company_alias, "_effective_resources", lambda *_: nodes)
    monkeypatch.setattr(source_company_alias, "inspect", lambda *_: {"accepted": False})
    return principal, nodes[binding], nodes, ids, content


def test_exact_source_pins_and_schema_without_financial_authority(monkeypatch):
    principal, binding, nodes, ids, content = setup(monkeypatch)
    before = deepcopy(nodes)
    result = source_snapshot.derive_snapshot(principal, binding, nodes.__getitem__)
    assert result.source_sha256 == sha256(content).hexdigest()
    assert result.source_rows == 1
    assert str(result.company.resource_id) == ids["company"]
    assert str(result.meaning.account_mapping.version_id) == nodes[ids["mapping"]]["version_id"]
    assert result.meaning.vat_treatment == "AS_POSTED"
    assert result.period_starts_on.isoformat() == "2025-01-01"
    assert nodes == before
    assert "total" not in result.model_dump()


def test_schema_is_independent_of_values_but_sensitive_to_layout():
    first = workbook()
    changed = workbook(replacement={"C2": "Another recorder"})
    relocated = workbook(headers={**HEADERS, "AC": "Different dimension meaning"})
    hashes = [
        source_snapshot._schema(value, "Base", "seg_expense_base", read_base(value))
        for value in (first, changed, relocated)
    ]
    assert hashes[0] == hashes[1]
    assert hashes[0] != hashes[2]


@pytest.mark.parametrize(
    "change",
    [
        "hash",
        "scope",
        "period",
        "company",
        "mapping",
        "account_version",
        "meaning",
        "profile",
        "binding",
    ],
)
def test_refuses_incompatible_retained_authority(monkeypatch, change):
    principal, binding, nodes, ids, _ = setup(monkeypatch)
    if change == "hash":
        nodes[ids["evidence"]]["attributes"]["sha256"] = "b" * 64
    elif change == "scope":
        nodes[ids["scope"]]["attributes"]["observed_through"] = "2025-01-02"
    elif change == "period":
        nodes[ids["period"]]["attributes"]["starts_on"] = "2025-01-02"
    elif change == "company":
        nodes[ids["company"]]["display_name"] = "Different company"
    elif change == "mapping":
        del nodes[ids["mapping"]]["attributes"]["definition"]["accounts"]["3110"]
    elif change == "account_version":
        nodes[ids["mapping"]]["attributes"]["definition"]["accounts"]["3110"]["version_id"] = str(
            uuid4()
        )
    elif change == "meaning":
        binding["attributes"]["source_use"] = "REVIEW_CANDIDATE"
    elif change == "profile":
        nodes[ids["scope"]]["attributes"]["source_profile"] = "unknown"
    else:
        binding = deepcopy(binding)
        binding["version_id"] = str(uuid4())
    with pytest.raises(WorkspaceError):
        source_snapshot.derive_snapshot(principal, binding, nodes.__getitem__)


def test_ambiguous_extra_headers_are_refused():
    content = workbook(headers={**HEADERS, "AO": "Classification"})
    with pytest.raises(WorkspaceError, match="unambiguous"):
        source_snapshot._schema(content, "Base", "seg_expense_base", read_base(content))


@pytest.mark.parametrize("amount", ["", '<c r="S2"><f>AD2</f><v>821.66</v></c>'])
def test_absent_or_formula_amount_preserves_row_and_missing_coordinate(monkeypatch, amount):
    buffer = BytesIO()
    with ZipFile(BytesIO(workbook())) as original, ZipFile(buffer, "w") as changed:
        for name in original.namelist():
            content = original.read(name)
            if name.endswith("sheet1.xml"):
                content = content.replace(b'<c r="S2"><v>731.97</v></c>', amount.encode())
            changed.writestr(name, content)
    principal, binding, nodes, _, _ = setup(monkeypatch, buffer.getvalue())
    result = source_snapshot.derive_snapshot(principal, binding, nodes.__getitem__)
    assert result.source_rows == result.missing_amount_count == 1
    assert result.missing_amount_coordinates == ["Base!S2"]
    assert result.coverage_state == "UNESTABLISHED"


@pytest.mark.parametrize("stale", [False, True])
def test_later_company_alias_requires_exact_reviewed_pin(monkeypatch, stale):
    principal, binding, nodes, ids, _ = setup(monkeypatch)
    company = nodes[ids["company"]]
    company["display_name"] = "Existing canonical company"
    alias_id = str(uuid4())
    alias = {
        "resource_id": alias_id,
        "version_id": str(uuid4()),
        "content_hash": "b" * 64,
        "object_type": "Alias",
        "evidence_class": "USER_ASSERTED",
        "attributes": {},
    }
    nodes[alias_id] = alias
    nodes[ids["scope"]]["attributes"]["company_alias_id"] = alias_id
    reviewed = deepcopy(alias)
    if stale:
        reviewed["version_id"] = str(uuid4())
    monkeypatch.setattr(
        source_company_alias,
        "inspect",
        lambda *_: {
            "accepted": True,
            "alias": reviewed,
            "company": company,
        },
    )
    if stale:
        with pytest.raises(WorkspaceError, match="exact reviewed company alias"):
            source_snapshot.derive_snapshot(principal, binding, nodes.__getitem__)
    else:
        result = source_snapshot.derive_snapshot(principal, binding, nodes.__getitem__)
        assert str(result.company_alias.resource_id) == alias_id
        assert str(result.company.resource_id) == ids["company"]


def test_parser_amount_roles_are_explicit_and_missing_is_not_zero():
    parsed = {
        "rows": [{"row": 8, "attributes": {}}, {"row": 9, "attributes": {"opening_debit": "0"}}]
    }
    assert source_snapshot._missing_amounts(parsed, "1c_tb", "TB", "opening_debit") == ["TB!G8"]
    with pytest.raises(WorkspaceError, match="cannot observe"):
        source_snapshot._missing_amounts(parsed, "1c_tb", "TB", "headline_total")


def test_missing_observation_coordinate_list_is_bounded_at_snapshot_boundary(monkeypatch):
    principal, binding, nodes, _, _ = setup(monkeypatch)
    missing = [f"Base!S{row}" for row in range(2, 103)]
    # Bound reporting independently from a (synthetic) larger complete source.
    parsed = read_base(workbook())
    parsed["rows"] = [{**deepcopy(parsed["rows"][0]), "row": row} for row in range(2, 103)]
    monkeypatch.setattr(source_snapshot, "read_base", lambda *_: parsed)
    monkeypatch.setattr(source_snapshot, "_missing_amounts", lambda *_: missing)
    result = source_snapshot.derive_snapshot(principal, binding, nodes.__getitem__)
    assert result.source_rows == result.missing_amount_count == 101
    assert result.missing_amount_coordinates == missing[:100]


@pytest.mark.parametrize("profile", ["1c_tb", "1c_journal"])
def test_legacy_schema_uses_headers_and_roles_without_period_or_company_values(
    monkeypatch, profile
):
    cells = {(1, 10): "Dr Account", (1, 16): "Cr Account", (1, 22): "Сумма"}
    if profile == "1c_tb":
        cells = {(5, 6): "Сальдо на начало периода", (6, 2): "Код", (6, 3): "Наименование"}
    source = SimpleNamespace(
        ncols=23,
        merged_cells=[],
        cell_value=lambda r, c: cells.get((r, c), ""),
        cell_type=lambda *_: source_snapshot.xlrd.XL_CELL_TEXT,
    )
    book = SimpleNamespace(sheet_by_name=lambda _: source, release_resources=lambda: None)
    monkeypatch.setattr(source_snapshot.xlrd, "open_workbook", lambda **_: book)
    first = source_snapshot._schema(b"synthetic", "Sheet", profile, {})
    cells[2, 2] = "Different report period/company content"
    assert source_snapshot._schema(b"different bytes", "Sheet", profile, {}) == first
    cells[6 if profile == "1c_tb" else 1, 22] = "Changed header role"
    assert source_snapshot._schema(b"synthetic", "Sheet", profile, {}) != first
