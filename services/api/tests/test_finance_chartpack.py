"""Reusable ChartPack and unreviewed classification proofs."""

from pathlib import Path

import pytest

from finai_api.services.finance_chartpack import (
    classification_manifest,
    classify_account,
    load_chartpack,
)
from finai_api.services.independent_tb_reader import mark_overlaps, read_tb_path


@pytest.fixture(scope="module")
def january():
    path = Path(r"D:\download c\TB\SGP 1.xls")
    if not path.is_file():
        pytest.skip("private SGP fixture directory is not available")
    return mark_overlaps(read_tb_path(path))


def test_chartpack_is_data_and_maps_1c_group_codes():
    pack = load_chartpack()
    assert pack.pack_id == "chartpack.1c_ge_statutory.v1"
    assert pack.mapping_status == "proposed"
    assert classify_account("6110", pack=pack).local_account_class == "revenue"
    assert classify_account("6110", pack=pack).flow_measure == "turnover_credit"
    assert (
        classify_account("141X", subkonto="1234567", pack=pack).analytic_dimension
        == "site_analytic"
    )
    assert (
        classify_account("141X", subkonto="Acme", pack=pack).analytic_dimension
        == "counterparty_analytic"
    )


def test_january_7410_classification_retains_non_additive_duplicates(january):
    pack = load_chartpack()
    rows = {row.source_row: row for row in january.rows}
    for source_row in (2832, 2834, 2860):
        classification = classify_account(
            rows[source_row].account_code,
            subkonto=rows[source_row].subkonto,
            additive_ok=rows[source_row].additive_ok,
            duplicate_of=rows[source_row].duplicate_of,
            pack=pack,
        )
        assert classification.state == "CLASSIFICATION_UNREVIEWED"
        assert classification.local_account_class == "administrative_expense"
        assert classification.additive_ok is (source_row == 2832)
        assert classification.duplicate_of == (None if source_row == 2832 else 2832)


def test_classification_manifest_pins_pack_and_source_hash(january):
    manifest = classification_manifest(
        january.rows,
        source_family="sf_test",
        source_hashes=[january.source_sha256],
    )
    assert manifest["mapping_status"] == "proposed"
    assert manifest["classification_state"] == "CLASSIFICATION_UNREVIEWED"
    assert manifest["source_hashes"] == [january.source_sha256]
    row = next(item for item in manifest["accounts"] if item["account_code"] == "7410")
    assert row["additive_ok"] is False or row["source_rows"] == [2832]
