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


def test_source_observations_cannot_masquerade_as_bound_financial_facts():
    observation = row("001", "2025-01-31", "10")
    observation["object_type"] = "SourceJournalMovement"
    with pytest.raises(WorkspaceError, match="require ledger, unit and representation"):
        aggregate_rows(contract(), [observation], "schema", [], None)


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


def revised(**changes):
    return FactContract.model_validate({**contract().model_dump(), **changes})


def test_cumulative_values_are_selected_not_accumulated_again():
    rows = [row("A", "2025-01-31", "100"), row("A", "2025-02-28", "250")]
    spec = revised(aggregation="cumulative_snapshot")
    with pytest.raises(WorkspaceError, match="snapshot date"):
        aggregate_rows(spec, rows, "schema", [], date(2025, 2, 28))
    assert aggregate_rows(spec, rows[1:], "schema", [], date(2025, 2, 28))[0]["value"] == "250"


def test_margin_is_ratio_of_components_not_average_of_percentages():
    rows = [row("A", "2025-01-31", "10"), row("B", "2025-01-31", "90")]
    for r, revenue in zip(rows, ("100", "300"), strict=True):
        r["attributes"]["revenue"] = revenue
    spec = revised(aggregation="ratio_of_sums", denominator_measure="revenue", ratio_multiplier=100)
    result = aggregate_rows(spec, rows, "schema", [], None)[0]
    assert result["value"] == "25.000000"  # Not (10% + 30%) / 2.
    assert result["components"] == {"numerator": "100", "denominator": "400"}
    rows[0]["attributes"]["revenue"] = "0"
    assert aggregate_rows(spec, rows[:1], "schema", [], None)[0]["value"] is None


def test_accounting_partitions_cannot_be_removed_by_group_selection():
    spec = revised(
        grain=["account", "date", "currency", "company", "tax_basis"],
        partition_fields=["company", "tax_basis"],
    )
    rows = [row("A", "2025-01-31", "100"), row("A", "2025-01-31", "118")]
    for r, company, tax in zip(rows, ("SGP", "SGG"), ("NET", "GROSS"), strict=True):
        r["attributes"].update(company=company, tax_basis=tax)
    groups = aggregate_rows(spec, rows, "schema", [], None)
    assert len(groups) == 2
    assert {g["value"] for g in groups} == {"100", "118"}


def test_source_controls_and_parent_child_overlap_are_not_summed():
    rows = [row("1000", "2025-01-31", "100"), row("1100", "2025-01-31", "100")]
    rows[0]["attributes"].update(role="CONTROL", parent=None)
    rows[1]["attributes"].update(role="DETAIL", parent="1000")
    with pytest.raises(WorkspaceError, match="selected row role"):
        aggregate_rows(
            revised(row_role_field="role", included_row_role="DETAIL"), rows, "schema", [], None
        )
    with pytest.raises(WorkspaceError, match="Parent and child"):
        aggregate_rows(
            revised(hierarchy_key_field="account", parent_key_field="parent"),
            rows,
            "schema",
            [],
            None,
        )


def test_gl_and_sales_are_compared_without_adding_or_hiding_missing_coordinates():
    from finai_api.domain.ontology_definitions import FactReconciliation
    from finai_api.services.fact_reconciliation import compare_groups

    spec = FactReconciliation(
        group_by=["account"],
        absolute_tolerance="0.01",
        authority_side="left",
        relationship="OVERLAPPING_REPRESENTATION",
        rationale="GL authority reconciled with sales detail",
    )
    left = [{"dimensions": {"account": "revenue", "currency": "GEL"}, "value": "100"}]
    right = [*left, {"dimensions": {"account": "other", "currency": "GEL"}, "value": "5"}]
    result = compare_groups(spec, left, right)
    matched = next(r for r in result if r["state"] == "MATCHED")
    assert matched["designated_authority"]["value"] == "100"
    assert matched["difference"] == "0"
    assert next(r for r in result if r["state"] == "MISSING_LEFT")["difference"] is None
