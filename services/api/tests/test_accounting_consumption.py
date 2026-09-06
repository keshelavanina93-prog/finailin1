from uuid import uuid4

import pytest

from finai_api.services.accounting_consumption import validate_bindings
from finai_api.services.workspace import WorkspaceError


def fixture_graph():
    rows, edges = {}, []

    def node(kind, attrs, evidence="USER_ASSERTED"):
        key = (uuid4(), uuid4())
        rows[key] = {
            "object_type": kind,
            "attributes": attrs,
            "authority_state": "APPROVED",
            "evidence_class": evidence,
        }
        return key

    company, chart, calendar, evidence_id = [str(uuid4()) for _ in range(4)]
    currency = node("Currency", {"code": "GEL"})
    ledger = node(
        "Ledger",
        {
            "legal_entity_id": company,
            "chart_id": chart,
            "calendar_id": calendar,
            "currency_id": str(currency[0]),
        },
    )
    book = node("AccountingBook", {"ledger_id": str(ledger[0])})
    period = node(
        "FiscalPeriod",
        {"calendar_id": calendar, "starts_on": "2026-01-01", "ends_on": "2026-01-31"},
    )
    mapping = node("MappingVersion", {})
    scope = node(
        "SourceAccountingScope",
        {
            "legal_entity_id": company,
            "chart_id": chart,
            "evidence_id": evidence_id,
            "observed_from": "2026-01-01",
            "observed_through": "2026-01-31",
            "source_profile": "1c_journal",
        },
        "SOURCE_BOUND",
    )
    binding = node(
        "SourceAccountingBinding",
        {
            "source_use": "ACCOUNTING_INPUT",
            "contract_version": "2",
            "currency_role": "FUNCTIONAL",
            "currency_policy": "SOURCE_AMOUNT_ONLY",
            "granularity": "SOURCE_ROW",
            "deepest_valid_drill": "SOURCE_ROW",
            "amount_field": "amount",
            "amount_semantics": "SIGNED_MOVEMENT",
            "rationale": "Explicit isolated synthetic accounting interpretation",
        },
    )
    for field, target in {
        "scope_id": scope,
        "ledger_id": ledger,
        "book_id": book,
        "period_id": period,
        "currency_id": currency,
        "functional_currency_id": currency,
        "account_mapping_id": mapping,
        "dimension_mapping_id": mapping,
    }.items():
        rows[binding]["attributes"][field] = str(target[0])
        edges.append((binding, target, "FIELD:" + field))
    source = node(
        "SourceJournalMovement",
        {
            "legal_entity_id": company,
            "evidence_id": evidence_id,
            "posting_date": "2026-01-15",
            "amount": "12",
        },
        "SOURCE_BOUND",
    )
    derived = node("CustomAmountFact", {"amount": "12"}, "SOURCE_BOUND")
    edges.append((derived, source, "SOURCE"))
    return rows, edges, {derived}, {derived, binding}, source, binding


def test_accounting_is_detected_through_derived_lineage_and_pinned_binding():
    rows, edges, used, direct, _, binding = fixture_graph()
    assert validate_bindings(rows, edges, used, direct) == [
        {"resource_id": str(binding[0]), "version_id": str(binding[1])}
    ]
    with pytest.raises(WorkspaceError, match="direct consumer dependency"):
        validate_bindings(rows, edges, used, used)


@pytest.mark.parametrize("change", ["company", "date", "currency", "review", "v1", "pin"])
def test_incompatible_or_unresolved_binding_cannot_authorize_accounting(change):
    rows, edges, used, direct, source, binding = fixture_graph()
    if change == "company":
        rows[source]["attributes"]["legal_entity_id"] = str(uuid4())
    elif change == "date":
        rows[source]["attributes"]["posting_date"] = "2026-02-01"
    elif change == "currency":
        rows[source]["attributes"]["amount"] = {"amount": "12", "currency": "USD"}
    elif change == "review":
        rows[binding]["attributes"]["source_use"] = "REVIEW_CANDIDATE"
    elif change == "v1":
        rows[binding]["attributes"]["contract_version"] = "1"
    else:
        edges = [edge for edge in edges if edge[2] != "FIELD:scope_id"]
    with pytest.raises(WorkspaceError):
        validate_bindings(rows, edges, used, direct)


def test_generic_fact_without_accounting_ancestry_remains_supported():
    rows, _, used, _, _, _ = fixture_graph()
    assert validate_bindings({key: rows[key] for key in used}, [], used, used) == []


def test_derived_fact_cannot_relabel_the_accounting_currency():
    rows, edges, used, direct, _, _ = fixture_graph()
    derived = next(iter(used))
    rows[derived]["attributes"]["amount"] = {"amount": "12", "currency": "USD"}
    with pytest.raises(WorkspaceError, match="derived accounting currency"):
        validate_bindings(rows, edges, used, direct)


def test_canonical_money_uses_currency_identity():
    rows, edges, used, direct, source, binding = fixture_graph()
    amount = {"amount": "12", "currency_id": rows[binding]["attributes"]["currency_id"]}
    rows[source]["attributes"]["amount"] = amount
    rows[next(iter(used))]["attributes"]["amount"] = amount
    assert validate_bindings(rows, edges, used, direct)
