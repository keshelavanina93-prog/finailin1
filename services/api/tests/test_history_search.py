"""Discovery preserves temporal selection and exact, authorized company ownership."""

import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from finai_api.services.history_search import project, search
from finai_api.services.workspace import WorkspaceError

JAN = datetime(2026, 1, 1, tzinfo=UTC)
FEB = datetime(2026, 2, 1, tzinfo=UTC)
MAR = datetime(2026, 3, 1, tzinfo=UTC)


def row(kind="LegalEntity", label="Company", **changes):
    return {
        "resource_id": uuid4(),
        "version_id": uuid4(),
        "object_type": kind,
        "identity_key": "synthetic:" + uuid4().hex,
        "display_name": label,
        "access_entity": "synthetic",
        "schema_version_id": None,
        "attributes": {},
        "content_hash": "0" * 64,
        "valid_from": JAN,
        "valid_to": None,
        "system_from": JAN,
        "authority_state": "APPROVED",
        "evidence_class": "REFERENCE_TEMPLATE",
        "proposal_id": None,
        **changes,
    }


def pin(source, target, field):
    source["attributes"][field] = str(target["resource_id"])
    return {
        "version_id": source["version_id"],
        "target_version_id": target["version_id"],
        "target_resource_id": target["resource_id"],
        "relation": "FIELD:" + field,
    }


def test_company_ownership_exact_pins_and_page_boundaries():
    company, other = row(), row(label="Other company")
    chart, account, other_account = (
        row("LocalChartOfAccounts", "A Chart"),
        row("LocalAccount", "B Account"),
        row("LocalAccount", "Other account"),
    )
    forged = row(
        "LocalAccount",
        "Unpinned account",
        attributes={"legal_entity_id": str(company["resource_id"])},
    )
    pins = [
        pin(chart, company, "legal_entity_id"),
        pin(account, chart, "chart_id"),
        pin(other_account, other, "legal_entity_id"),
    ]
    rows = [company, other, chart, account, other_account, forged]
    result = project(rows, pins, company["resource_id"], MAR, "", None, 0, 2)
    assert [r["display_name"] for r in result["resources"]] == ["A Chart", "B Account"]
    assert result["has_more"]
    assert result["matched_count"] == 3
    assert result["type_facets"] == [
        {"object_type": "LegalEntity", "count": 1},
        {"object_type": "LocalAccount", "count": 1},
        {"object_type": "LocalChartOfAccounts", "count": 1},
    ]
    last = project(rows, pins, company["resource_id"], MAR, "", None, 2, 2)
    assert [r["display_name"] for r in last["resources"]] == ["Company"]
    assert not last["has_more"]
    assert last["type_facets"] == result["type_facets"]
    assert last["matched_count"] == 3
    # Removing an accessible exact target cannot be bypassed using its resource identity.
    denied = project([company, account], pins, company["resource_id"], MAR, "", None, 0, 50)
    assert len(denied["resources"]) == 1


def test_asof_latest_precedes_label_filter_and_preserves_revocation():
    company = row()
    old = row("Ledger", "Old label")
    old_pin = pin(old, company, "legal_entity_id")
    corrected = {
        **old,
        "version_id": uuid4(),
        "system_from": FEB,
        "display_name": "New label",
        "authority_state": "REVOKED",
    }
    new_pin = pin(corrected, company, "legal_entity_id")
    result = project(
        [company, old, corrected],
        [old_pin, new_pin],
        company["resource_id"],
        MAR,
        "Old label",
        None,
        0,
        50,
    )
    assert result["resources"] == []
    assert result["type_facets"] == []
    assert result["matched_count"] == 0
    result = project(
        [company, old, corrected],
        [old_pin, new_pin],
        company["resource_id"],
        MAR,
        "new",
        "Ledger",
        0,
        50,
    )
    assert result["resources"][0]["authority_state"] == "REVOKED"
    assert result["type_facets"] == [{"object_type": "Ledger", "count": 1}]
    future = {**corrected, "valid_from": MAR}
    result = project(
        [company, old, future], [old_pin, new_pin], company["resource_id"], FEB, "old", None, 0, 50
    )
    assert result["resources"][0]["version_id"] == str(old["version_id"])
    assert result["type_facets"] == [{"object_type": "Ledger", "count": 1}]
    with pytest.raises(WorkspaceError, match="Company is unavailable"):
        project([old], [], company["resource_id"], MAR, "", None, 0, 50)


def test_facets_follow_name_and_exact_ownership_but_not_selected_type_or_page():
    company, other = row(), row(label="Other")
    ledger = row("Ledger", "Finance ledger")
    book = row("AccountingBook", "Finance book")
    unrelated = row("Ledger", "Finance other company")
    unpinned = row(
        "Ledger", "Finance unpinned", attributes={"company_id": str(company["resource_id"])}
    )
    pins = [
        pin(ledger, company, "legal_entity_id"),
        pin(book, ledger, "ledger_id"),
        pin(unrelated, other, "legal_entity_id"),
    ]
    rows = [company, other, ledger, book, unrelated, unpinned]
    result = project(rows, pins, company["resource_id"], MAR, " FINANCE ", "Ledger", 0, 1)
    assert result["matched_count"] == 1
    assert result["resources"][0]["version_id"] == str(ledger["version_id"])
    assert result["type_facets"] == [
        {"object_type": "AccountingBook", "count": 1},
        {"object_type": "Ledger", "count": 1},
    ]
    empty = project(rows, pins, company["resource_id"], MAR, "Finance", "Licence", 4, 1)
    assert empty["resources"] == []
    assert empty["matched_count"] == 0
    assert empty["type_facets"] == result["type_facets"]


def test_facets_do_not_resurrect_identity_reassigned_to_another_company():
    company, other = row(), row(label="Other")
    old = row("Ledger", "Finance ledger")
    old_pin = pin(old, company, "legal_entity_id")
    replacement = {**old, "version_id": uuid4(), "system_from": FEB, "attributes": {}}
    new_pin = pin(replacement, other, "legal_entity_id")
    result = project(
        [company, other, old, replacement],
        [old_pin, new_pin],
        company["resource_id"],
        MAR,
        "Finance",
        None,
        0,
        50,
    )
    assert result["matched_count"] == 0
    assert result["type_facets"] == []


@pytest.mark.skipif(os.environ.get("G8_BINDING_DB_TEST") != "1", reason="Opt-in PostgreSQL")
def test_postgres_knowledge_time_and_tenant_isolation():
    from test_historical_graph import accept, node

    from finai_api.domain.authority import ExactScope
    from finai_api.domain.review import Principal

    principal = Principal(
        actor_id="synthetic-history-search",
        display_name="Synthetic history search",
        scope=ExactScope(
            tenant_id=UUID("805d8a32-d12b-4268-a236-b0b16e59da9f"),
            legal_entity_id="synthetic-search-" + uuid4().hex,
            period="2026-09",
            currency="GEL",
        ),
        permissions=("ontology_read", "ontology_propose", "ontology_review"),
    )
    actors = (principal, principal.model_copy(update={"actor_id": "independent-search-review"}))
    original = node("LegalEntity", "search original", {})
    company = accept(actors, [original])[0]
    replacement = accept(
        actors,
        [
            original.model_copy(
                update={
                    "expected_version_id": company.version_id,
                    "display_name": "SYNTHETIC search corrected",
                }
            )
        ],
    )[0]
    historical = search(
        principal, company.resource_id, known_at=company.system_from, effective_at=MAR
    )
    assert historical["resources"][0]["version_id"] == str(company.version_id)
    assert historical["matched_count"] == 1
    assert historical["type_facets"] == [{"object_type": "LegalEntity", "count": 1}]
    latest = search(
        principal, company.resource_id, known_at=replacement.system_from, effective_at=MAR
    )
    assert latest["resources"][0]["version_id"] == str(replacement.version_id)
    assert latest["matched_count"] == 1
    assert latest["type_facets"] == historical["type_facets"]
    assert latest["current_use_authorized"] is False
    chart_mutation = node(
        "LocalChartOfAccounts",
        "discovery chart",
        {"legal_entity_id": str(company.resource_id), "code": "SYNTHETIC"},
    )
    chart = accept(actors, [chart_mutation])[0]
    account = accept(
        actors,
        [
            node(
                "LocalAccount",
                "discovery account",
                {"chart_id": str(chart.resource_id), "account_code": "001"},
            )
        ],
    )[0]
    categorized = search(
        principal, company.resource_id, q="DISCOVERY", object_type="LocalAccount", limit=1
    )
    assert categorized["matched_count"] == 1
    assert categorized["type_facets"] == [
        {"object_type": "LocalAccount", "count": 1},
        {"object_type": "LocalChartOfAccounts", "count": 1},
    ]
    assert categorized["resources"][0]["version_id"] == str(account.version_id)
    for query in (str(account.resource_id).upper(), account.identity_key):
        exact = search(principal, company.resource_id, q=query)
        assert exact["matched_count"] == 1
        assert exact["resources"][0]["version_id"] == str(account.version_id)
    distant_page = search(principal, company.resource_id, q="discovery", offset=5001, limit=1)
    assert distant_page["resources"] == []
    assert distant_page["matched_count"] == 2
    assert distant_page["type_facets"] == categorized["type_facets"]
    other = accept(actors, [node("LegalEntity", "discovery other company", {})])[0]
    assert search(principal, company.resource_id, q=str(other.resource_id))["matched_count"] == 0
    accept(
        actors,
        [
            chart_mutation.model_copy(
                update={
                    "expected_version_id": chart.version_id,
                    "attributes": {"legal_entity_id": str(other.resource_id), "code": "SYNTHETIC"},
                }
            )
        ],
    )
    moved = search(
        principal, company.resource_id, q="discovery", object_type="LocalChartOfAccounts"
    )
    assert moved["matched_count"] == 0
    assert moved["resources"] == []
    # Account retains its exact old chart/company pin; current chart identity is not substituted.
    assert moved["type_facets"] == [{"object_type": "LocalAccount", "count": 1}]
    before_move = search(
        principal, company.resource_id, q="discovery", known_at=account.system_from
    )
    assert before_move["matched_count"] == 2
    assert before_move["type_facets"] == categorized["type_facets"]
    denied = principal.model_copy(
        update={
            "scope": principal.scope.model_copy(
                update={"legal_entity_id": "unrelated-" + uuid4().hex}
            )
        }
    )
    with pytest.raises(WorkspaceError, match="Company is unavailable"):
        search(denied, company.resource_id, effective_at=MAR)
    other_tenant = principal.model_copy(
        update={"scope": principal.scope.model_copy(update={"tenant_id": uuid4()})}
    )
    with pytest.raises(WorkspaceError, match="Company is unavailable"):
        search(other_tenant, company.resource_id, effective_at=MAR)
