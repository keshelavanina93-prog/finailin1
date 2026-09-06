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
    last = project(rows, pins, company["resource_id"], MAR, "", None, 2, 2)
    assert [r["display_name"] for r in last["resources"]] == ["Company"]
    assert not last["has_more"]
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
    future = {**corrected, "valid_from": MAR}
    result = project(
        [company, old, future], [old_pin, new_pin], company["resource_id"], FEB, "old", None, 0, 50
    )
    assert result["resources"][0]["version_id"] == str(old["version_id"])
    with pytest.raises(WorkspaceError, match="Company is unavailable"):
        project([old], [], company["resource_id"], MAR, "", None, 0, 50)


@pytest.mark.skipif(os.environ.get("G8_BINDING_DB_TEST") != "1", reason="Opt-in PostgreSQL")
def test_postgres_knowledge_time_and_tenant_isolation(monkeypatch):
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
    # Platform and unrelated histories exceed this bound; this company's two versions
    # must remain searchable because the database scopes ownership before applying it.
    monkeypatch.setattr("finai_api.services.history_search.MAX_VERSIONS", 3)
    historical = search(
        principal, company.resource_id, known_at=company.system_from, effective_at=MAR
    )
    assert historical["resources"][0]["version_id"] == str(company.version_id)
    latest = search(
        principal, company.resource_id, known_at=replacement.system_from, effective_at=MAR
    )
    assert latest["resources"][0]["version_id"] == str(replacement.version_id)
    assert latest["current_use_authorized"] is False
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
