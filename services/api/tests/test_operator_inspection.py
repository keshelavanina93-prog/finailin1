"""Operator detail preserves knowledge time, exact version pins and existing isolation."""

import os
from datetime import datetime
from uuid import UUID, uuid4

import pytest

from finai_api.domain.authority import ExactScope
from finai_api.domain.review import Principal
from finai_api.services.operator_inspection import inspect
from finai_api.services.workspace import WorkspaceError


def principal():
    return Principal(
        actor_id="synthetic-inspection-author",
        display_name="Synthetic inspection author",
        scope=ExactScope(
            tenant_id=UUID("805d8a32-d12b-4268-a236-b0b16e59da9f"),
            legal_entity_id="inspection-" + uuid4().hex,
            period="2026-09",
            currency="GEL",
        ),
        permissions=("ontology_read", "ontology_propose", "ontology_review"),
    )


def test_naive_knowledge_time_rejected_before_database():
    with pytest.raises(WorkspaceError, match="timezone") as error:
        inspect(principal(), uuid4(), known_at=datetime(2026, 1, 1))
    assert error.value.status == 422


@pytest.mark.skipif(os.environ.get("G8_BINDING_DB_TEST") != "1", reason="Opt-in PostgreSQL")
def test_exact_inspector_filters_later_versions_and_dependents_with_native_rls(monkeypatch):
    from fastapi.testclient import TestClient
    from test_historical_graph import accept, node

    from finai_api.main import app
    from finai_api.security import authenticated_principal
    from finai_api.services import operator_inspection

    author = principal()
    actors = author, author.model_copy(update={"actor_id": "independent-inspection-reviewer"})
    mutation = node("LegalEntity", "inspection original", {})
    original = accept(actors, [mutation])[0]
    old_chart = accept(
        actors,
        [
            node(
                "LocalChartOfAccounts",
                "first dependent",
                {"legal_entity_id": str(original.resource_id), "code": "FIRST"},
            )
        ],
    )[0]
    later = accept(
        actors,
        [
            mutation.model_copy(
                update={
                    "expected_version_id": original.version_id,
                    "display_name": "SYNTHETIC later known",
                }
            )
        ],
    )[0]
    new_chart = accept(
        actors,
        [
            node(
                "LocalChartOfAccounts",
                "second dependent",
                {"legal_entity_id": str(original.resource_id), "code": "SECOND"},
            )
        ],
    )[0]
    result = inspect(author, original.resource_id, original.version_id, old_chart.system_from)
    assert result["resource"]["version_id"] == str(original.version_id)
    assert [v["version_id"] for v in result["versions"]] == [str(original.version_id)]
    assert {v["version_id"] for v in result["dependents"]} == {old_chart.version_id}
    assert result["known_at"] == old_chart.system_from.isoformat()
    assert result["current_use_authorized"] is False
    no_dependents_yet = inspect(
        author, original.resource_id, original.version_id, original.system_from
    )
    assert no_dependents_yet["dependents"] == []
    latest_known = inspect(author, original.resource_id, known_at=old_chart.system_from)
    assert latest_known["resource"]["version_id"] == str(original.version_id)
    assert latest_known["selection_mode"] == "LATEST_KNOWN"
    with pytest.raises(WorkspaceError) as hidden_future:
        inspect(author, original.resource_id, later.version_id, old_chart.system_from)
    assert hidden_future.value.status == 404
    exact_old_now = inspect(author, original.resource_id, original.version_id)
    assert {v["version_id"] for v in exact_old_now["dependents"]} == {old_chart.version_id}
    exact_new = inspect(author, original.resource_id, later.version_id)
    assert {v["version_id"] for v in exact_new["dependents"]} == {new_chart.version_id}
    denied = author.model_copy(
        update={
            "scope": author.scope.model_copy(
                update={
                    "legal_entity_id": "unrelated-" + uuid4().hex,
                }
            )
        }
    )
    other_tenant = author.model_copy(
        update={
            "scope": author.scope.model_copy(
                update={
                    "tenant_id": uuid4(),
                }
            )
        }
    )
    for reader in (denied, other_tenant):
        with pytest.raises(WorkspaceError) as unavailable:
            inspect(reader, original.resource_id, original.version_id)
        assert unavailable.value.status == 404
    monkeypatch.setattr(operator_inspection, "MAX_VERSIONS", 1)
    bounded = inspect(author, original.resource_id, original.version_id)
    assert bounded["versions_truncated"] is True
    assert len(bounded["versions"]) == 1
    assert bounded["resource"]["version_id"] == str(original.version_id)
    prior_override = app.dependency_overrides.get(authenticated_principal)
    app.dependency_overrides[authenticated_principal] = lambda: author
    try:
        with TestClient(app) as client:
            response = client.get(
                f"/v1/ontology/operator/resources/{original.resource_id}",
                params={
                    "version_id": str(original.version_id),
                    "known_at": old_chart.system_from.isoformat(),
                },
            )
            assert response.status_code == 200
            assert response.json()["dependents"][0]["version_id"] == str(old_chart.version_id)
            assert response.json()["known_at"] == old_chart.system_from.isoformat()
    finally:
        if prior_override is None:
            app.dependency_overrides.pop(authenticated_principal, None)
        else:
            app.dependency_overrides[authenticated_principal] = prior_override
