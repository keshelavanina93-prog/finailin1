"""Bounded, coordinate-preserving XLS views of retained originals."""

import xlrd

from finai_api.domain.review import Principal
from finai_api.services.source_documents import document_bytes
from finai_api.services.workspace import WorkspaceError


def preview(
    principal: Principal, identity: str, sheet_name: str | None, offset: int, limit: int = 50
) -> dict:
    if offset < 0 or not 1 <= limit <= 50:
        raise WorkspaceError(422, "Worksheet page requires a nonnegative offset and 1-50 rows")
    metadata, content = document_bytes(principal, identity)
    try:
        book = xlrd.open_workbook(file_contents=content, on_demand=True)
        try:
            names = book.sheet_names()
            if sheet_name is None:
                return {
                    "document_id": identity,
                    "sha256": metadata["source_sha256"],
                    "sheets": names,
                }
            sheet = book.sheet_by_name(sheet_name)
            if sheet.ncols > 256:
                raise WorkspaceError(422, "Sheet exceeds the 256-column preview limit")
            rows = []
            for index in range(offset, min(offset + limit, sheet.nrows)):
                cells = []
                for column in range(sheet.ncols):
                    cell = sheet.cell(index, column)
                    # Empty, numeric, date serial and error cells stay distinct. No subtotal
                    # removal, decimal rounding, formula reconstruction or zero filling.
                    cells.append(
                        {
                            "coordinate": f"{sheet_name}!{xlrd.colname(column)}{index + 1}",
                            "type": cell.ctype,
                            "value": cell.value,
                        }
                    )
                rows.append({"row": index + 1, "cells": cells})
            return {
                "document_id": identity,
                "sha256": metadata["source_sha256"],
                "sheets": names,
                "sheet": sheet_name,
                "row_count": sheet.nrows,
                "column_count": sheet.ncols,
                "date_mode": book.datemode,
                "rows": rows,
                "offset": offset,
                "next_offset": offset + limit if offset + limit < sheet.nrows else None,
                "authority": "SOURCE_CELLS_ONLY",
            }
        finally:
            book.release_resources()
    except (xlrd.XLRDError, IndexError) as exc:
        raise WorkspaceError(422, "Preview requires a readable XLS workbook and worksheet") from exc
