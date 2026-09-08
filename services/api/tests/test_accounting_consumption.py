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


@pytest.mark.parametrize("posting_date", ["2026-01-16", "2030-12-31"])
def test_derived_fact_cannot_relabel_source_posting_date(posting_date):
    rows, edges, used, direct, _, _ = fixture_graph()
    rows[next(iter(used))]["attributes"]["posting_date"] = posting_date
    with pytest.raises(WorkspaceError, match="posting date disagrees"):
        validate_bindings(rows, edges, used, direct)


def test_derived_fact_preserves_exact_source_date_and_bound_period():
    rows, edges, used, direct, source, binding = fixture_graph()
    attrs = rows[next(iter(used))]["attributes"]
    attrs["posting_date"] = rows[source]["attributes"]["posting_date"]
    attrs["period_id"] = rows[binding]["attributes"]["period_id"]
    assert validate_bindings(rows, edges, used, direct)
    attrs["period_id"] = str(uuid4())
    with pytest.raises(WorkspaceError, match="derived accounting context"):
        validate_bindings(rows, edges, used, direct)


def test_source_explicit_period_cannot_disagree_with_binding():
    rows, edges, used, direct, source, _ = fixture_graph()
    rows[source]["attributes"]["period_id"] = str(uuid4())
    with pytest.raises(WorkspaceError, match="incompatible active bindings"):
        validate_bindings(rows, edges, used, direct)


def test_multi_date_aggregate_preserves_period_without_fabricated_posting_date():
    from copy import deepcopy

    rows, edges, used, direct, source, binding = fixture_graph()
    other = (uuid4(), uuid4())
    rows[other] = deepcopy(rows[source])
    rows[other]["attributes"]["posting_date"] = "2026-01-16"
    derived = next(iter(used))
    edges.append((derived, other, "SOURCE"))
    rows[derived]["attributes"].update(
        amount="24", period_id=rows[binding]["attributes"]["period_id"]
    )
    assert validate_bindings(rows, edges, used, direct)
    rows[derived]["attributes"]["posting_date"] = "2026-01-15"
    with pytest.raises(WorkspaceError, match="posting date disagrees"):
        validate_bindings(rows, edges, used, direct)


def canonical_graph():
    """Canonical header/lines use the source binding without copying source amounts."""
    rows, edges, _, _, source, binding = fixture_graph()
    config = rows[binding]["attributes"]
    config["amount_field"] = "source_amount"
    source_attrs = rows[source]["attributes"]
    rows[source]["object_type"] = "SourceRecord"
    source_attrs.pop("amount")
    line_ids = [uuid4(), uuid4()]
    header = (uuid4(), uuid4())
    rows[header] = {
        "object_type": "JournalEntry",
        "authority_state": "APPROVED",
        "attributes": {
            "accounting_binding_id": str(binding[0]),
            "legal_entity_id": source_attrs["legal_entity_id"],
            "ledger_id": config["ledger_id"],
            "period_id": config["period_id"],
            "posting_date": source_attrs["posting_date"],
            "definition": {"contract": "balanced-journal/1", "line_ids": list(map(str, line_ids))},
        },
    }
    scope = next(
        row["attributes"] for row in rows.values() if row["object_type"] == "SourceAccountingScope"
    )
    account = (uuid4(), uuid4())
    rows[account] = {
        "object_type": "LocalAccount",
        "authority_state": "APPROVED",
        "attributes": {"chart_id": scope["chart_id"]},
    }
    lines = []
    edges.append((header, binding, "FIELD:accounting_binding_id"))
    for identity, side in zip(line_ids, ("DEBIT", "CREDIT"), strict=True):
        line = (identity, uuid4())
        rows[line] = {
            "object_type": "JournalLine",
            "authority_state": "APPROVED",
            "attributes": {
                "accounting_binding_id": str(binding[0]),
                "journal_id": str(header[0]),
                "source_record_id": str(source[0]),
                "account_id": str(account[0]),
                "side": side,
                "amount": {"amount": "12.01", "currency_id": config["currency_id"]},
            },
        }
        for target, field in (
            (binding, "accounting_binding_id"),
            (header, "journal_id"),
            (source, "source_record_id"),
            (account, "account_id"),
        ):
            edges.append((line, target, "FIELD:" + field))
        lines.append(line)
    return rows, edges, binding, header, lines, source, account


def test_canonical_journal_consumption_preserves_measure_free_header_and_line_money():
    from copy import deepcopy

    rows, edges, binding, header, lines, _, _ = canonical_graph()
    before = deepcopy(rows)
    result = validate_bindings(rows, edges, {header, *lines}, {binding})
    assert result == [{"resource_id": str(binding[0]), "version_id": str(binding[1])}]
    assert rows == before
    assert "amount" not in rows[header]["attributes"]
    assert "source_amount" not in rows[lines[0]]["attributes"]


@pytest.mark.parametrize(
    "change",
    [
        "line_company",
        "line_evidence",
        "line_date",
        "line_currency",
        "line_membership",
        "source_evidence",
        "account_chart",
        "header_period",
        "header_date",
        "header_company",
        "line_authority",
        "header_authority",
        "manifest",
        "source_pin",
    ],
)
def test_canonical_journal_cannot_relabel_or_omit_exact_context(change):
    rows, edges, binding, header, lines, source, account = canonical_graph()
    attrs = rows[lines[0]]["attributes"]
    if change == "line_company":
        attrs["legal_entity_id"] = str(uuid4())
    elif change == "line_evidence":
        attrs["evidence_id"] = str(uuid4())
    elif change == "line_date":
        attrs["posting_date"] = "2026-01-16"
    elif change == "line_currency":
        attrs["amount"]["currency_id"] = str(uuid4())
    elif change == "line_membership":
        rows[header]["attributes"]["definition"]["line_ids"][0] = str(uuid4())
    elif change == "source_evidence":
        rows[source]["attributes"]["evidence_id"] = str(uuid4())
    elif change == "account_chart":
        rows[account]["attributes"]["chart_id"] = str(uuid4())
    elif change == "header_period":
        rows[header]["attributes"]["period_id"] = str(uuid4())
    elif change == "header_date":
        rows[header]["attributes"]["posting_date"] = "2026-02-01"
    elif change == "header_company":
        rows[header]["attributes"]["legal_entity_id"] = str(uuid4())
    elif change == "line_authority":
        rows[lines[0]]["authority_state"] = "REVOKED"
    elif change == "header_authority":
        rows[header]["authority_state"] = "REVOKED"
    elif change == "manifest":
        rows[header]["attributes"]["definition"]["line_ids"] = []
    else:
        edges = [edge for edge in edges if edge[1] != source]
    with pytest.raises(WorkspaceError):
        validate_bindings(rows, edges, set(lines), {binding})


def test_journal_ancestry_does_not_exempt_private_derived_amount():
    rows, edges, binding, _, lines, _, _ = canonical_graph()
    derived = (uuid4(), uuid4())
    rows[derived] = {"object_type": "PrivateFinancialSummary", "attributes": {}}
    edges.extend((derived, line, "INPUT") for line in lines)
    with pytest.raises(WorkspaceError, match="amount"):
        validate_bindings(rows, edges, {derived}, {binding})
