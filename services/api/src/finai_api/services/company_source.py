"""Source-column company observations, without inferred registration or ownership."""


import xlrd

from finai_api.domain.review import Principal
from finai_api.services.source_documents import document_bytes
from finai_api.services.workspace import WorkspaceError


def observe_companies(content: bytes, sheet_name: str, header_row: int, column: int) -> dict:
    if not content.startswith(bytes.fromhex("d0cf11e0a1b11ae1")):
        raise WorkspaceError(422, "Company-column inspection currently supports BIFF XLS sources")
    try:
        book = xlrd.open_workbook(file_contents=content, on_demand=True)
        try:
            sheet = book.sheet_by_name(sheet_name)
            if sheet.nrows > 100000 or sheet.ncols > 256:
                raise WorkspaceError(422, "Source sheet exceeds the company inspection limit")
            if not 1 <= header_row < sheet.nrows or not 1 <= column <= sheet.ncols:
                raise WorkspaceError(
                    422, "Source header row or column is outside the selected sheet"
                )
            header = str(sheet.cell_value(header_row - 1, column - 1)).strip()
            if not header:
                raise WorkspaceError(422, "Select a labelled company column")
            if header.casefold() not in {
                "company-eng",
                "company",
                "organization",
                "организация",
                "კომპანია",
                "ორგანიზაცია",
            }:
                raise WorkspaceError(422, "The selected header is not a recognized company field")
            groups: dict[str, list[int]] = {}
            blank_rows = []
            for row in range(header_row, sheet.nrows):
                value = sheet.cell_value(row, column - 1)
                if value == "":
                    if any(sheet.row_values(row)):
                        blank_rows.append(row + 1)
                    continue
                if sheet.cell_type(row, column - 1) != xlrd.XL_CELL_TEXT:
                    raise WorkspaceError(422, "Company names require text cells")
                label = value.strip()
                if not label or len(label) > 200:
                    raise WorkspaceError(422, "Company label is empty or exceeds 200 characters")
                groups.setdefault(label, []).append(row + 1)
                if len(groups) > 30:
                    raise WorkspaceError(
                        422, "More than 30 company labels; narrow the source sheet"
                    )
            return {
                "sheet": sheet_name,
                "header_row": header_row,
                "column": column,
                "header": header,
                "companies": [
                    {
                        "source_label": label,
                        "row_count": len(rows),
                        "first_coordinate": f"{sheet_name}!{xlrd.colname(column - 1)}{rows[0]}",
                    }
                    for label, rows in sorted(groups.items())
                ],
                "unassigned_row_count": len(blank_rows),
                "authority": "SOURCE_COMPANY_LABELS_ONLY",
            }
        finally:
            book.release_resources()
    except (xlrd.XLRDError, IndexError) as exc:
        raise WorkspaceError(422, "Workbook or selected company sheet cannot be read") from exc


def inspect_companies(
    principal: Principal,
    document_id: str,
    sheet: str,
    header_row: int,
    column: int,
    mode: str = "company_column",
) -> dict:
    document, content = document_bytes(principal, document_id)
    return {
        "document_id": document_id,
        "sha256": document["source_sha256"],
        **(
            observe_tb_company(content, sheet)
            if mode == "1c_tb_title"
            else observe_companies(content, sheet, header_row, column)
        ),
    }


def observe_tb_company(content: bytes, sheet_name: str) -> dict:
    """Recognize the original 1C TB title; never interpret it as a journal row."""
    try:
        book = xlrd.open_workbook(file_contents=content, on_demand=True)
        try:
            sheet = book.sheet_by_name(sheet_name)
            if sheet.nrows < 7 or sheet.ncols < 3:
                raise WorkspaceError(422, "The selected sheet is not a recognized 1C trial balance")
            if str(sheet.cell_value(1, 2)).strip() != "Оборотно-сальдовая ведомость":
                raise WorkspaceError(422, "The 1C trial balance title is missing at C2")
            label = sheet.cell_value(0, 2)
            if not isinstance(label, str) or not 1 <= len(label.strip()) <= 200:
                raise WorkspaceError(422, "A company title is required at C1")
            return {
                "sheet": sheet_name,
                "mode": "1c_tb_title",
                "companies": [
                    {
                        "source_label": label.strip(),
                        "row_count": 1,
                        "first_coordinate": f"{sheet_name}!C1",
                    }
                ],
                "unassigned_row_count": 0,
                "authority": "SOURCE_COMPANY_LABELS_ONLY",
            }
        finally:
            book.release_resources()
    except (xlrd.XLRDError, IndexError) as exc:
        raise WorkspaceError(422, "Workbook or selected company sheet cannot be read") from exc


def propose_companies(
    principal: Principal,
    document_id: str,
    sheet: str,
    header_row: int,
    column: int,
    mode: str = "company_column",
):
    # A source column can contain a region, branch or reporting label. Its text
    # alone cannot establish a legal company, even after generic proposal review.
    raise WorkspaceError(
        410,
        "Source labels cannot create legal entities. Review an explicit company identity "
        "and match the retained label through the existing source-company Alias workflow.",
    )
