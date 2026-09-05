import base64
import io
from uuid import uuid4
from zipfile import ZipFile

import pytest

from finai_api.domain.authority import ExactScope
from finai_api.domain.ingest import IngestRequest
from finai_api.services.ingestion import SourceAuthorityDenied, compile_source
from finai_api.services.report_inputs import ReportInputRequest, assess
from finai_api.services.workbook_source import profile_workbook, read_workbook


def workbook(cells: str, name: str = "Base") -> bytes:
    target = io.BytesIO()
    with ZipFile(target, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="' + name + '" sheetId="1" r:id="r1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="r1" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
            + cells
            + "</sheetData></worksheet>",
        )
    return target.getvalue()


def request(content: bytes, **options):
    return IngestRequest(
        scope=ExactScope(
            tenant_id=uuid4(), legal_entity_id="seg", period="2026-01", currency="GEL"
        ),
        filename="renamed.xlsx",
        xlsx_base64=base64.b64encode(content).decode(),
        **options,
    )


def text(address, value):
    return f'<c r="{address}" t="inlineStr"><is><t>{value}</t></is></c>'


def base():
    return workbook(
        '<row r="1">'
        + "".join(
            text(a + "1", v)
            for a, v in zip(
                ["A", "B", "C", "D", "E", "L"],
                ["Period", "Line number", "Recorder", "Организация", "Account Dr", "Account Cr"],
                strict=True,
            )
        )
        + '</row><row r="2">'
        + text("A2", "01.01.2025 0:00:00")
        + text("B2", "1")
        + text("C2", "doc1")
        + text("D2", "SEG")
        + text("E2", "7310.02.1")
        + text("L2", "3110")
        + '<c r="S2"><v>100</v></c><c r="AD2"><f>S2+18</f><v>118</v></c>'
        '<c r="AH2" t="e"><v>#N/A</v></c></row>'
    )


def test_observed_context_reference_role_errors_and_no_postings():
    r = compile_source(request(base()))
    assert r.rejects and r.source_profile["sheets"][0]["periods"] == ["2025-01"]
    assert r.source_profile["sheets"][0]["company_labels"] == ["SEG"]
    assert "WORKBOOK_ERROR_CELLS" in {f["code"] for f in r.source_profile["findings"]}
    assert {c.object_type for c in r.candidates} == {"SourceRecord"}
    reference = compile_source(request(base(), source_use="HISTORICAL_REFERENCE"))
    assert not reference.rejects
    with pytest.raises(SourceAuthorityDenied):
        compile_source(request(base(), requested_objects=("JournalEntry",)))
    assessment = assess(
        ReportInputRequest(
            period="2026-01",
            company_label="SEG",
            currency="GEL",
            receipt_ids=(reference.receipt_id,),
        ),
        [reference],
    )
    assert "REFERENCE_ONLY" in assessment["inputs"][0]["excluded_reasons"]
    assert all(line["state"] == "UNAVAILABLE" for line in assessment["lines"])


def test_cells_and_formulas_preserved_without_execution_and_sheet_identity_ignores_filename():
    b = read_workbook(base())
    assert b["sheets"][0]["cells"]["AD2"]["formula"] == "S2+18"
    assert b["sheets"][0]["cells"]["AD2"]["value"] == "118"
    assert (
        profile_workbook(b)["sheets"][0]["content_sha256"]
        == profile_workbook(read_workbook(base()))["sheets"][0]["content_sha256"]
    )
    with pytest.raises(ValueError):
        read_workbook(b"not zip")
    with pytest.raises(ValueError):
        read_workbook(workbook('<!DOCTYPE unsafe><row r="1"/>'))


def test_numeric_report_rows_are_not_account_mapping_rows():
    content = workbook(
        "".join(
            '<row r="'
            + str(r)
            + '">'
            + text("B" + str(r), str(r))
            + text("E" + str(r), "other")
            + "</row>"
            for r in range(1, 6)
        ),
        "Report",
    )
    assert profile_workbook(read_workbook(content))["sheets"][0]["source_type"] == "OTHER_TABULAR"
