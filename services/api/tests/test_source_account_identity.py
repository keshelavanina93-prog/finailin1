from types import SimpleNamespace

import pytest
import xlrd

from finai_api.services.source_account_binding import account_code
from finai_api.services.workspace import WorkspaceError


def read(value, fmt, kind=xlrd.XL_CELL_NUMBER):
    cell = SimpleNamespace(value=value, ctype=kind, xf_index=0)
    book = SimpleNamespace(
        xf_list=[SimpleNamespace(format_key=0)], format_map={0: SimpleNamespace(format_str=fmt)}
    )
    sheet = SimpleNamespace(cell=lambda row, column: cell)
    return account_code(book, sheet, 0, 0)


def test_account_identity_preserves_excel_display_precision_and_leading_zeroes():
    assert read(3340.1, "0.00") == "3340.10"
    assert read(12, "0000") == "0012"
    assert read("0012.10", "General", xlrd.XL_CELL_TEXT) == "0012.10"


def test_account_identity_never_rounds_or_guesses_fractional_general_format():
    with pytest.raises(WorkspaceError):
        read(3340.125, "0.00")
    with pytest.raises(WorkspaceError):
        read(3340.1, "General")
