"""Exact finance results, missing coverage, source provenance and policy separation."""

from copy import deepcopy
from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from finai_api.domain.authority import ExactScope
from finai_api.domain.finance_execution import (
    FinanceExecutionRequest,
    FinanceProjectionDefinition,
)
from finai_api.domain.object_sets import ObjectSetQuery
from finai_api.domain.ontology_definitions import FactContract
from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.services import finance_execution as finance
from finai_api.services.workspace import WorkspaceError


def ref(number):
    return VersionReference(resource_id=UUID(int=number), version_id=UUID(int=number + 10000))


def scope():
    return ExactScope(
        tenant_id=UUID(int=1), legal_entity_id="SGP", period="2026-02", currency="GEL"
    )


def spec(**changes):
    values = dict(
        grain=["account_id", "starts_on", "ends_on", "currency", "ledger"],
        dimensions=["account_id", "starts_on", "ends_on", "ledger"],
        measure="amount",
        aggregation="flow_sum",
        time_field="ends_on",
        period_start_field="starts_on",
        unit_field="currency",
        source_family="REVIEWED_GL",
        source_family_field="family",
        partition_fields=["ledger"],
        authority_basis="Reviewed test representation only",
    )
    values.update(changes)
    return FactContract.model_validate(values)


def request(operation="ytd_flow", **changes):
    now = datetime(2026, 3, 1, tzinfo=UTC)
    values = dict(
        operation=operation,
        contract=ref(10),
        query=ObjectSetQuery(object_type="AccountPeriodFact", valid_at=now, known_at=now),
        starts_on=date(2026, 1, 1),
        as_of=date(2026, 2, 28),
    )
    values.update(changes)
    return FinanceExecutionRequest(**values)


def row(number, account=21, amount="0.1", start="2026-01-01", end="2026-01-31", **attributes):
    return {
        **ref(number).model_dump(mode="json"),
        "schema_version_id": str(ref(11).version_id),
        "object_type": "AccountPeriodFact",
        "evidence_class": "SOURCE_BOUND",
        "access_entity": "SGP",
        "authority_state": "APPROVED",
        "attributes": {
            "account_id": str(ref(account).resource_id),
            "starts_on": start,
            "ends_on": end,
            "amount": amount,
            "currency": "GEL",
            "family": "REVIEWED_GL",
            "ledger": "ACTUAL",
            **attributes,
        },
    }


def calculate(rows, operation="ytd_flow", fact=None, projection=None, **kwargs):
    return finance.calculate(
        fact or spec(), rows, str(ref(11).version_id), request(operation, **kwargs), projection
    )


def projection(code="CORPORATE_MR"):
    return FinanceProjectionDefinition(
        projection_code=code,
        exact_scope=scope(),
        fact_contract=ref(10),
        company=ref(12),
        chart=ref(13),
        evidence=ref(14),
        starts_on=date(2026, 1, 1),
        ends_on=date(2026, 2, 28),
        source_family="REVIEWED_GL",
        account_field="account_id",
        unit_value="GEL",
        rationale="Explicit reviewed reporting policy",
        expected_accounts=[ref(21), ref(22)],
        rules=[
            dict(
                account=ref(21),
                reporting_line=ref(31),
                multiplier="1",
                rationale="Reviewed revenue mapping",
            ),
            dict(
                account=ref(22),
                reporting_line=ref(31),
                multiplier="-1",
                rationale="Reviewed cost sign mapping",
            ),
        ],
    )


def complete_rows():
    return [
        row(101, amount="0.1"),
        row(102, amount="0.2", start="2026-02-01", end="2026-02-28"),
        row(103, account=22, amount="0.01"),
        row(104, account=22, amount="0.02", start="2026-02-01", end="2026-02-28"),
    ]


def test_ytd_exact_amounts_preserve_every_source_and_mandatory_ledger():
    rows = complete_rows()
    result = calculate(rows)
    assert [group.value for group in result.groups] == ["0.3", "0.03"]
    assert result.state == "DERIVED"
    assert result.coverage == "EXPLICIT_PERIOD_INTERVALS"
    assert result.groups[0].dimensions["ledger"] == "ACTUAL"
    assert result.groups[0].dimensions["currency"] == "GEL"
    assert result.groups[0].inputs == [ref(101), ref(102)]
    assert result.business_effect_authorized is False
    assert result.financial_certification is None


def test_period_gap_is_missing_never_a_zero_filled_total():
    result = calculate([row(101)])
    assert result.state == "INCOMPLETE"
    assert result.groups[0].value is None
    assert result.groups[0].observed_value == "0.1"
    assert result.groups[0].missing == ["MISSING_INTERVAL:2026-02-01:2026-02-28"]
    assert calculate([]).state == "UNAVAILABLE"


@pytest.mark.parametrize("aggregation", ["closing_balance", "cumulative_snapshot", "non_additive"])
def test_ytd_never_accumulates_snapshots(aggregation):
    fact = spec(aggregation=aggregation, period_start_field=None)
    with pytest.raises(WorkspaceError, match="never cumulative/YTD"):
        calculate([row(101)], fact=fact)


def test_overlapping_ytd_intervals_and_source_duplicates_fail():
    with pytest.raises(WorkspaceError, match="Overlapping"):
        calculate([row(101), row(102, start="2026-01-01", end="2026-02-28")])
    with pytest.raises(WorkspaceError, match="repeats an exact source"):
        calculate([row(101), row(101)])
    with pytest.raises(WorkspaceError, match="Duplicate fact grain"):
        calculate([row(101), row(102)])


@pytest.mark.parametrize("amount", [0.1, 10, True, None, "NaN", "Infinity", "1e300", "1e-300"])
def test_financial_inputs_refuse_floats_nonfinite_and_missing(amount):
    with pytest.raises(WorkspaceError):
        calculate([row(101, amount=amount)])


def test_no_unreviewed_source_family_or_wrong_schema_enters_aggregation():
    with pytest.raises(WorkspaceError, match="source family"):
        calculate([row(101, family="SALES")])
    changed = row(101)
    changed["schema_version_id"] = str(ref(12).version_id)
    with pytest.raises(WorkspaceError, match="schema differs"):
        calculate([changed])
    changed = row(101)
    changed["evidence_class"] = "USER_ASSERTED"
    with pytest.raises(WorkspaceError, match="user-asserted"):
        calculate([changed])


def test_closing_balance_requires_exact_snapshot_and_keeps_currency_separate():
    fact = spec(aggregation="closing_balance", period_start_field=None)
    result = calculate(
        [
            row(101, end="2026-02-28", amount="100"),
            row(102, end="2026-02-28", amount="90", currency="USD"),
        ],
        operation="closing_as_of",
        fact=fact,
        starts_on=None,
    )
    assert {group.dimensions["currency"]: group.value for group in result.groups} == {
        "GEL": "100",
        "USD": "90",
    }
    with pytest.raises(WorkspaceError, match="snapshot date"):
        calculate([row(101)], operation="closing_as_of", fact=fact, starts_on=None)
    with pytest.raises(WorkspaceError, match="closing-balance contract"):
        calculate([row(101)], operation="closing_as_of")


def test_journal_to_trial_balance_computes_turnover_without_inventing_opening_balance():
    fact = spec(
        grain=["account_id", "line_id", "ends_on", "currency", "ledger", "side"],
        dimensions=["account_id", "ends_on", "ledger", "side"],
        period_start_field=None,
    )
    rows = [
        row(101, amount="0.1", line_id="L1", side="DEBIT"),
        row(102, amount="0.2", line_id="L2", side="DR"),
        row(103, amount="0.05", line_id="L3", side="CREDIT"),
    ]
    result = calculate(rows, operation="trial_balance", fact=fact, side_field="side")
    group = result.groups[0]
    assert group.debit_turnover == "0.3"
    assert group.credit_turnover == "0.05"
    assert group.value == "0.25"
    assert group.opening_balance is None and group.closing_balance is None
    assert "OPENING_BALANCE_NOT_SUPPLIED" in group.missing
    rows[0]["attributes"]["side"] = "UNKNOWN"
    with pytest.raises(WorkspaceError, match="debit or credit"):
        calculate(rows, operation="trial_balance", fact=fact, side_field="side")


def test_parent_reconciliation_compares_does_not_double_count():
    fact = spec(hierarchy_key_field="account_id", parent_key_field="parent")
    rows = [
        row(101, account=20, amount="0.3"),
        row(102, amount="0.1", parent=str(ref(20).resource_id)),
        row(103, account=22, amount="0.2", parent=str(ref(20).resource_id)),
    ]
    result = calculate(rows, operation="reconcile_parent", fact=fact)
    assert result.groups == []
    assert result.state == "MATCHED"
    assert result.comparisons[0]["parent_value"] == "0.3"
    assert result.comparisons[0]["child_value"] == "0.3"
    assert result.comparisons[0]["difference"] == "0.0"
    assert len(result.comparisons[0]["children"]) == 2
    rows[0]["attributes"]["amount"] = "0.4"
    assert calculate(rows, operation="reconcile_parent", fact=fact).state == "UNRECONCILED"
    assert (
        calculate(rows[1:], operation="reconcile_parent", fact=fact).comparisons[0]["state"]
        == "MISSING_PARENT"
    )
    rows[0]["attributes"]["parent"] = str(ref(21).resource_id)
    with pytest.raises(WorkspaceError, match="cycle"):
        calculate(rows, operation="reconcile_parent", fact=fact)


@pytest.mark.parametrize("code", ["CORPORATE_MR", "PETROLEUM_PNL", "GAS"])
def test_separate_reviewed_projections_compute_explicit_signed_mapping(code):
    policy = projection(code)
    result = finance.calculate(
        spec(),
        complete_rows(),
        str(ref(11).version_id),
        request("project", projection=ref(40)),
        policy,
    )
    assert result.groups[0].value == "0.27"
    assert result.groups[0].dimensions["projection_code"] == code
    assert result.groups[0].dimensions["reporting_line_id"] == str(ref(31).resource_id)
    assert len(result.groups[0].inputs) == 4


def test_unmapped_missing_and_incomplete_accounts_never_produce_complete_report_totals():
    policy = projection()
    rows = [*complete_rows()[:2], row(105, account=23)]
    result = finance.calculate(
        spec(), rows, str(ref(11).version_id), request("project", projection=ref(40)), policy
    )
    assert result.state == "INCOMPLETE"
    assert result.missing_accounts == [str(ref(22).resource_id)]
    assert result.unmapped_accounts == [str(ref(23).resource_id)]
    assert result.groups[0].value is None
    assert result.groups[0].observed_value == "0.3"
    with pytest.raises(WorkspaceError, match="exact fact contract or coverage"):
        finance.calculate(
            spec(),
            rows,
            str(ref(11).version_id),
            request("project", projection=ref(40), contract=ref(99)),
            policy,
        )


def test_projection_model_rejects_duplicate_account_fanout_and_mismatched_versions():
    data = projection().model_dump(mode="json")
    data["rules"].append(data["rules"][0])
    with pytest.raises(ValidationError, match="one leaf line"):
        FinanceProjectionDefinition.model_validate(data)
    data = projection().model_dump(mode="json")
    data["expected_accounts"][0]["version_id"] = str(UUID(int=99))
    with pytest.raises(ValidationError, match="same account versions"):
        FinanceProjectionDefinition.model_validate(data)


def projection_nodes(policy):
    nodes = {}
    for relation, selected, kind in finance.projection_references(policy):
        nodes[str(selected.resource_id)] = {
            **selected.model_dump(mode="json"),
            "object_type": kind,
            "authority_state": "APPROVED",
            "access_entity": "SGP",
            "attributes": {},
            "relation": relation,
        }
    nodes[str(ref(13).resource_id)]["attributes"] = {"legal_entity_id": str(ref(12).resource_id)}
    for identity in (21, 22):
        nodes[str(ref(identity).resource_id)]["attributes"] = {"chart_id": str(ref(13).resource_id)}
    nodes[str(ref(10).resource_id)]["attributes"] = {"definition": spec().model_dump(mode="json")}
    return nodes


def test_projection_publication_binds_exact_company_chart_account_evidence_versions():
    from finai_api.domain.resources import ResourceMutation

    policy = projection()
    mutation = ResourceMutation(
        object_type="FinanceProjectionDefinition",
        identity_key="corporate",
        display_name="Corporate MR",
        access_entity="SGP",
        attributes={"definition": policy.model_dump(mode="json")},
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
    )
    nodes = projection_nodes(policy)
    calls = []

    def target(identity, owner, relation, version):
        calls.append((identity, relation, version))
        assert nodes[identity]["version_id"] == version
        return nodes[identity]

    finance.validate_projection(mutation, target)
    assert len(calls) == 7
    nodes[str(ref(21).resource_id)]["attributes"]["chart_id"] = str(ref(99).resource_id)
    with pytest.raises(WorkspaceError, match="selected chart"):
        finance.validate_projection(mutation, target)
    nodes = projection_nodes(policy)
    nodes[str(ref(31).resource_id)]["access_entity"] = "OTHER"
    with pytest.raises(WorkspaceError, match="another company"):
        finance.validate_projection(mutation, target)


def test_request_rejects_unpinned_time_partial_queries_and_ignored_projection_inputs():
    data = request().model_dump(mode="json")
    data["query"]["known_at"] = None
    with pytest.raises(ValidationError, match="exact valid and known"):
        FinanceExecutionRequest.model_validate(data)
    data = request().model_dump(mode="json")
    data["query"]["offset"] = 50
    with pytest.raises(ValidationError, match="complete query"):
        FinanceExecutionRequest.model_validate(data)
    with pytest.raises(ValidationError, match="Only project"):
        request(projection=ref(40))


def test_core_does_not_mutate_source_facts_or_projection():
    rows, policy = complete_rows(), projection()
    before = deepcopy(rows)
    finance.calculate(
        spec(), rows, str(ref(11).version_id), request("project", projection=ref(40)), policy
    )
    assert rows == before


def test_projection_coverage_cannot_borrow_missing_accounts_across_ledgers():
    rows = complete_rows()
    for item in rows[2:]:
        item["attributes"]["ledger"] = "OTHER_LEDGER"
    result = finance.calculate(
        spec(), rows, str(ref(11).version_id), request("project", projection=ref(40)), projection()
    )
    assert result.state == "INCOMPLETE"
    assert len(result.groups) == 2
    assert all(group.value is None for group in result.groups)
    assert all(group.missing for group in result.groups)


def service_case(monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace

    from finai_api.domain.review import Principal

    principal = Principal(
        actor_id="reader", display_name="Reader", scope=scope(), permissions=("ontology_read",)
    )
    fact = {
        **ref(10).model_dump(mode="json"),
        "content_hash": "a" * 64,
        "object_type": "FactContract",
        "access_entity": "SGP",
        "attributes": {"definition": spec().model_dump(mode="json")},
        "dependencies": [
            {
                **ref(11).model_dump(mode="json"),
                "content_hash": "b" * 64,
                "relation": "FIELD:schema_id",
                "identity_key": "AccountPeriodFact",
            }
        ],
    }
    rows = complete_rows()
    definitions, authority, retained = [], [], []

    def definition(principal, identity, version):
        definitions.append((identity, version))
        return fact

    def query(principal, selected):
        return SimpleNamespace(total=len(rows), objects=rows, next_offset=None, query=selected)

    @contextmanager
    def cursor(**kwargs):
        yield None

    @contextmanager
    def connection(principal):
        yield SimpleNamespace(cursor=cursor)

    def retain(principal, result, *, runtime):
        retained.append((result, runtime))
        return {**result, "run_id": "fcr_" + "c" * 64}

    monkeypatch.setattr(finance.ontology_definitions, "definition", definition)
    monkeypatch.setattr(finance, "query_objects", query)
    monkeypatch.setattr(finance, "resource_connection", connection)
    monkeypatch.setattr(finance, "_current", lambda cursor, principal, selected: fact)
    monkeypatch.setattr(finance, "upstream_authority", lambda *args: authority.append(args))
    monkeypatch.setattr(finance.fact_runs, "retain_run", retain)
    return principal, fact, rows, definitions, authority, retained


def test_authorized_execution_uses_exact_definitions_and_existing_retained_fact_store(monkeypatch):
    principal, fact, rows, definitions, authority, retained = service_case(monkeypatch)
    result = finance.execute(principal, request())
    assert definitions == [(ref(10).resource_id, ref(10).version_id)]
    assert len(authority) == 1
    assert retained[0][1] == "finance-catalog/1"
    assert result["scope"] == principal.scope.model_dump(mode="json")
    assert result["fact_contract"]["content_hash"] == fact["content_hash"]
    assert result["groups"][0]["value"] == "0.3"
    assert len(result["source_versions"]) == len(rows)
    assert result["run_id"].startswith("fcr_")
    assert result["current_use_authorized"] is False


def test_execution_rejects_cross_company_fact_before_retention(monkeypatch):
    principal, _, rows, _, _, retained = service_case(monkeypatch)
    rows[0]["access_entity"] = "OTHER"
    with pytest.raises(WorkspaceError, match="outside the selected company"):
        finance.execute(principal, request())
    assert retained == []


def test_execution_rejects_wrong_query_schema_and_scope_period_before_retention(monkeypatch):
    principal, fact, _, _, _, retained = service_case(monkeypatch)
    with pytest.raises(WorkspaceError, match="invoking exact scope"):
        finance.execute(principal, request(as_of=date(2026, 3, 31)))
    fact["dependencies"][0]["identity_key"] = "SalesFact"
    with pytest.raises(WorkspaceError, match="exact fact schema"):
        finance.execute(principal, request())
    assert retained == []


def journal_case(monkeypatch):
    from finai_api.domain.finance_execution import CanonicalJournalTrialBalanceRequest
    from finai_api.services import company_journals

    principal, _, _, _, _, retained = service_case(monkeypatch)
    invocation = CanonicalJournalTrialBalanceRequest(
        company=ref(12),
        ledger=ref(50),
        book=ref(51),
        period=ref(52),
        snapshot_at=datetime(2026, 3, 1, tzinfo=UTC),
        starts_on=date(2026, 2, 1),
        as_of=date(2026, 2, 28),
    )
    selection = {
        "legal_entity_id": ref(12).model_dump(mode="json"),
        "ledger_id": ref(50).model_dump(mode="json"),
        "book_id": ref(51).model_dump(mode="json"),
        "period_id": ref(52).model_dump(mode="json"),
        "currency_id": ref(53).model_dump(mode="json"),
    }
    journal = {**ref(60).model_dump(mode="json"), "attributes": {"posting_date": "2026-02-10"}}
    lines = []
    for number, account, side in [(61, 21, "DEBIT"), (62, 22, "CREDIT")]:
        lines.append(
            {
                "line": {
                    **ref(number).model_dump(mode="json"),
                    "schema_version_id": str(ref(11).version_id),
                    "object_type": "JournalLine",
                    "evidence_class": "SOURCE_BOUND",
                    "access_entity": "SGP",
                    "attributes": {
                        "side": side,
                        "amount": {"amount": "0.3", "currency_id": str(ref(53).resource_id)},
                    },
                },
                "account": ref(account).model_dump(mode="json"),
                "source_record": ref(number + 10).model_dump(mode="json"),
                "dimensions": {"state": "COMPLETE", "assignments": []},
            }
        )
    detail = {
        "selection": selection,
        "snapshot_at": invocation.snapshot_at.isoformat(),
        "integrity": {"state": "COMPLETE_BALANCED"},
        "journal": journal,
        "binding": ref(63).model_dump(mode="json"),
        "lines": lines,
    }
    page = {
        "selection": selection,
        "snapshot_at": invocation.snapshot_at.isoformat(),
        "coverage": {"state": "COMPLETE"},
        "total": 1,
        "next_offset": None,
        "items": [{"journal": journal}],
    }
    calls = []
    monkeypatch.setattr(company_journals, "list_journals", lambda *args, **kwargs: page)

    def read_detail(*args, **kwargs):
        calls.append((args, kwargs))
        return detail

    monkeypatch.setattr(company_journals, "detail", read_detail)
    return principal, invocation, detail, page, calls, retained


def test_real_journal_adapter_resolves_existing_exact_bundles_and_retains_lineage(monkeypatch):
    principal, invocation, _detail, _, calls, retained = journal_case(monkeypatch)
    result = finance.execute_journal_trial_balance(principal, invocation)
    assert result["implementation_id"] == "finance.canonical-journal-turnover/1"
    assert [group["value"] for group in result["groups"]] == ["0.3", "-0.3"]
    assert result["groups"][0]["dimensions"]["book_id"] == str(invocation.book.resource_id)
    assert calls[0][0][-2:] == (ref(60).resource_id, ref(60).version_id)
    assert result["source_versions"][0]["journal"] == ref(60).model_dump(mode="json")
    assert result["source_versions"][0]["schema_version_id"] == str(ref(11).version_id)
    assert result["dimension_coverage"]["state"] == "COMPLETE"
    assert retained[0][1] == "finance-catalog/1"
    assert result["current_use_authorized"] is False


def test_journal_adapter_requires_complete_balanced_source_and_exact_selection(monkeypatch):
    principal, invocation, detail, page, _, retained = journal_case(monkeypatch)
    detail["integrity"]["state"] = "INCOMPLETE_OR_UNAVAILABLE"
    with pytest.raises(WorkspaceError, match="Incomplete or unbalanced"):
        finance.execute_journal_trial_balance(principal, invocation)
    detail["integrity"]["state"] = "COMPLETE_BALANCED"
    detail["lines"][0]["line"]["evidence_class"] = "USER_ASSERTED"
    with pytest.raises(WorkspaceError, match="source-bound"):
        finance.execute_journal_trial_balance(principal, invocation)
    page["selection"]["book_id"] = ref(99).model_dump(mode="json")
    with pytest.raises(WorkspaceError, match="selection changed"):
        finance.execute_journal_trial_balance(principal, invocation)
    assert retained == []


def test_journal_adapter_exposes_missing_dimensions_and_refuses_unresolved_journal_coverage(
    monkeypatch,
):
    principal, invocation, detail, page, _, _ = journal_case(monkeypatch)
    detail["lines"][0]["dimensions"]["state"] = "UNESTABLISHED"
    result = finance.execute_journal_trial_balance(principal, invocation, retain=False)
    assert result["dimension_coverage"]["state"] == "INCOMPLETE"
    assert len(result["dimension_coverage"]["incomplete_lines"]) == 1
    page["coverage"]["state"] = "UNRESOLVED"
    with pytest.raises(WorkspaceError, match="Unresolved canonical"):
        finance.execute_journal_trial_balance(principal, invocation)
