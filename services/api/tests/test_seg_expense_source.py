from io import BytesIO
from xml.sax.saxutils import escape
from zipfile import ZipFile

import pytest

from finai_api.services.seg_expense_source import read_base
from finai_api.services.workspace import WorkspaceError

HEADERS = {
    "A": "Period",
    "B": "Line number",
    "C": "Recorder",
    "D": "Организация",
    "E": "Account Dr",
    "F": "Extra dimension1 Dr",
    "I": "Валюта Dr",
    "J": "Валютная сумма Dr",
    "L": "Account Cr",
    "M": "Extra dimension1 Cr",
    "P": "Валюта Cr",
    "Q": "Валютная сумма Cr",
    "S": "Сумма",
    "AC": "Classification",
    "AD": "Amount",
    "AN": "VAT",
}


def text(coordinate, value):
    return f'<c r="{coordinate}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'


def workbook(*, headers=None, replacement=None, extra_row=""):
    values = {
        "A2": "01.01.2025 0:00:00",
        "C2": "Recorder SEG001",
        "D2": "სოკარ ენერჯი ჯორჯია // Сокар Энерджи Джорджия",
        "E2": "0012.01",
        "L2": "3110",
        "M2": "LTD SOCAR Georgia Petroleum",
        "P2": "USD",
        "AC2": "Expense",
    }
    values.update(replacement or {})
    cells = (
        '<row r="1">'
        + "".join(text(column + "1", label) for column, label in (headers or HEADERS).items())
        + '</row><row r="2">'
        + "".join(text(key, value) for key, value in values.items())
    )
    cells += (
        '<c r="B2"><v>1</v></c><c r="J2"><v>0</v></c>'
        '<c r="Q2"><v>45</v></c><c r="S2"><v>731.97</v></c>'
        '<c r="AD2"><v>821.6600000000001</v></c>'
        '<c r="AN2"><f>AD2-S2</f><v>89.69000000000005</v></c>'
        "</row>" + extra_row
    )
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Base" r:id="r1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships><Relationship Id="r1" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            "<sheetData>" + cells + "</sheetData></worksheet>",
        )
    return buffer.getvalue()


def test_exact_observations_do_not_become_accounting_amount_or_company_inference():
    result = read_base(workbook())
    row = result["rows"][0]
    assert result["company_label"] == "სოკარ ენერჯი ჯორჯია // Сокар Энерджи Джорджия"
    assert row["attributes"]["account_code"] == "0012.01"
    assert row["attributes"]["source_row_key"] == "Base!2"
    assert result["observed_from"] == result["observed_through"] == "2025-01-01"
    assert row["cells"]["Base!M2"]["value"] == "LTD SOCAR Georgia Petroleum"
    assert row["numeric_observations"]["source_amount"]["literal_decimal"] == "731.97"
    assert row["numeric_observations"]["annotated_amount"]["literal_decimal"] == "821.6600000000001"
    vat = row["numeric_observations"]["annotated_vat"]
    assert vat["formula"] == "AD2-S2"
    assert vat["cached_decimal"] == "89.69000000000005"
    assert vat["literal_decimal"] is None
    assert result["currency_observations"]["debit"] == []
    assert result["currency_observations"]["credit"][0]["value"] == "USD"
    assert "amount" not in row["attributes"]
    assert "currency" not in row["attributes"]
    assert result["amount_mapping"] is None
    assert result["accounting_mapping_available"] is False


def test_company_and_classification_are_observations_not_profile_name_inference():
    result = read_base(workbook(replacement={"D2": "Other source company", "AC2": "Income"}))
    assert result["company_label"] == "Other source company"
    assert result["rows"][0]["cells"]["Base!AC2"]["value"] == "Income"


@pytest.mark.parametrize("replacement", [{"A2": "01/02/2025"}, {"E2": ""}, {"D2": ""}])
def test_unresolved_scope_identity_or_date_is_not_silently_accepted(replacement):
    with pytest.raises(WorkspaceError):
        read_base(workbook(replacement=replacement))


def test_changed_or_ambiguous_headers_and_invalid_archives_are_refused():
    with pytest.raises(WorkspaceError, match="headers"):
        read_base(workbook(headers={**HEADERS, "S": "Unknown amount"}))
    with pytest.raises(WorkspaceError, match="Ambiguous"):
        read_base(workbook(headers={**HEADERS, "ZZ": "Account Dr"}))
    with pytest.raises(WorkspaceError, match="workbook"):
        read_base(b"not a workbook")
    with pytest.raises(WorkspaceError, match="sheet"):
        read_base(workbook(), sheet="Missing")
