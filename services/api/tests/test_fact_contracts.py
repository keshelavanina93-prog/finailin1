from datetime import date

import pytest

from finai_api.domain.ontology_definitions import FactContract
from finai_api.services.account_source import profile_accounts
from finai_api.services.fact_aggregation import aggregate_rows
from finai_api.services.workspace import WorkspaceError


def contract(aggregation="flow_sum"):
    return FactContract(
        grain=["account", "date", "currency"],
        dimensions=["account"],
        measure="amount",
        aggregation=aggregation,
        time_field="date",
        unit_field="currency",
        source_family="GL",
        source_family_field="family",
        authority_basis="Reviewed GL representation",
    )


def row(account, date_value, amount, currency="GEL"):
    return {
        "resource_id": f"{account}:{date_value}:{currency}",
        "version_id": "v1",
        "schema_version_id": "schema",
        "evidence_class": "SOURCE_BOUND",
        "attributes": {
            "account": account,
            "date": date_value,
            "amount": amount,
            "currency": currency,
            "family": "GL",
        },
    }


def test_flow_aggregation_preserves_currency_and_rejects_overlap():
    rows = [
        row("001", "2025-01-31", "0.1"),
        row("001", "2025-02-28", "0.2"),
        row("001", "2025-01-31", "9", "USD"),
    ]
    groups = aggregate_rows(contract(), rows, "schema", ["account"], None)
    assert {g["dimensions"]["currency"]: g["value"] for g in groups} == {"GEL": "0.3", "USD": "9"}
    with pytest.raises(WorkspaceError, match="Duplicate fact grain"):
        aggregate_rows(contract(), [*rows, rows[0]], "schema", [], None)


def test_balances_cannot_be_summed_across_months():
    rows = [row("001", "2025-01-31", "100"), row("001", "2025-02-28", "120")]
    with pytest.raises(WorkspaceError, match="snapshot date"):
        aggregate_rows(contract("closing_balance"), rows, "schema", [], date(2025, 2, 28))
    assert (
        aggregate_rows(contract("closing_balance"), rows[1:], "schema", [], date(2025, 2, 28))[0][
            "value"
        ]
        == "120"
    )


def test_missing_or_reference_inputs_never_become_financial_values():
    missing = row("001", "2025-01-31", None)
    with pytest.raises(WorkspaceError, match="Missing grain or measure"):
        aggregate_rows(contract(), [missing], "schema", [], None)
    reference = {**row("001", "2025-01-31", "100"), "evidence_class": "REFERENCE_TEMPLATE"}
    with pytest.raises(WorkspaceError, match="Reference"):
        aggregate_rows(contract(), [reference], "schema", [], None)


def test_account_headers_can_move_and_labels_do_not_imply_requiredness():
    def cell(value):
        return {"value": value, "formula": None}

    sheet = {
        "name": "Accounts",
        "cells": {
            "D3": cell("Код"),
            "F3": cell("Наименование"),
            "H3": cell("Субконто 1"),
            "D4": cell("001"),
            "F4": cell("Account name"),
            "H4": cell("(об) Подразделения"),  # noqa: RUF001 - literal 1C designation
            "D5": cell("001"),
            "F5": cell("Duplicate source definition"),
        },
    }
    result = profile_accounts(sheet)
    assert result is not None
    assert result["accounts"][0]["account_code"] == "001"
    assert result["accounts"][0]["analytics"][0]["source_label"] == "(об) Подразделения"  # noqa: RUF001
    assert result["accounts"][0]["required_dimension_policy"] == "UNESTABLISHED"
    assert result["findings"][0]["code"] == "DUPLICATE_ACCOUNT_CODE"
