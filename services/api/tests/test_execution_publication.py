"""Real PostgreSQL publication boundary; no financial/source acceptance inferred."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from finai_api.domain.authority import ExactScope
from finai_api.domain.review import Principal
from finai_api.services import execution_publication as publication
from finai_api.services import report_workflows as records
from finai_api.services.workspace import WorkspaceError


@pytest.fixture
def retained_run():
    if os.environ.get("FINAI_PUBLICATION_DB_CHECK") != "1":
        pytest.skip("Opt in to publication verification against a local migrated PostgreSQL")
    principal = Principal(
        actor_id="publication-verification",
        display_name="Verification",
        scope=ExactScope(
            tenant_id=uuid4(), legal_entity_id="verification", period="2026-09", currency="GEL"
        ),
        permissions=("read", "ingest"),
    )

    def create(outputs):
        identity = "verification_" + uuid4().hex
        definition = {"version": "verification/1", "nodes": [], "outputs": outputs}
        with records.scope_connection(principal) as conn:
            scope = records.set_scope(conn, principal)
            conn.execute(
                "INSERT INTO workflow_requests "
                "(tenant_id,workflow_id,exact_scope,actor_id,definition_version,payload) "
                "VALUES(%s,%s,%s,%s,%s,%s)",
                (
                    principal.scope.tenant_id,
                    identity,
                    Jsonb(scope),
                    principal.actor_id,
                    definition["version"],
                    Jsonb({"definition": definition}),
                ),
            )
        return principal, identity

    return create


@pytest.mark.parametrize(
    "contract",
    [
        {"hierarchy": "source-hierarchy/1", "coverage": "source-assessment/1"},
        {"measurements": "operational-series/1", "exceptions": "quality-rejects/1"},
    ],
)
def test_complete_set_retry_conflict_and_generation_isolation(retained_run, contract):
    principal, identity = retained_run(contract)
    slots = list(contract)
    publication.stage(principal, identity, 0, slots[0], contract[slots[0]], {"count": 3})
    with pytest.raises(WorkspaceError, match="incomplete"):
        publication.publish(principal, identity, 0)
    assert publication.published(records.read(principal, identity)) == []
    publication.stage(principal, identity, 0, slots[1], contract[slots[1]], {"count": 0})
    # Concurrent/retried commits converge to the same immutable publication.
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: publication.publish(principal, identity, 0), range(2)))
    assert results[0] == results[1]
    assert results[0]["authority"] == "EXECUTION_ONLY"
    assert len(publication.published(records.read(principal, identity))) == 1
    with pytest.raises(WorkspaceError, match="conflicts"):
        publication.stage(principal, identity, 0, slots[0], contract[slots[0]], {"count": 4})
    publication.stage(principal, identity, 1, slots[0], contract[slots[0]], {"count": 4})
    with pytest.raises(WorkspaceError, match="incomplete"):
        publication.publish(principal, identity, 1)
    assert publication.published(records.read(principal, identity)) == [results[0]]


def test_timeout_after_commit_recovers_and_scope_and_permission_are_enforced(
    retained_run, monkeypatch
):
    principal, identity = retained_run({"data": "dataset-reference/1"})
    publication.stage(principal, identity, 0, "data", "dataset-reference/1", {"id": "retained"})
    original = records.event

    def committed_then_disconnected(*args):
        original(*args)
        raise ConnectionError("Injected lost acknowledgment after commit")

    monkeypatch.setattr(records, "event", committed_then_disconnected)
    with pytest.raises(ConnectionError):
        publication.publish(principal, identity, 0)
    monkeypatch.setattr(records, "event", original)
    result = publication.publish(principal, identity, 0)
    assert publication.published(records.read(principal, identity)) == [result]
    other = principal.model_copy(
        update={"scope": principal.scope.model_copy(update={"legal_entity_id": "other-entity"})}
    )
    with pytest.raises(WorkspaceError, match="unavailable"):
        publication.publish(other, identity, 0)
    denied = principal.model_copy(update={"permissions": ("read",)})
    with pytest.raises(HTTPException) as exc:
        publication.publish(denied, identity, 0)
    assert exc.value.status_code == 403


def test_contract_mismatch_and_legacy_definition_cannot_publish(retained_run):
    principal, identity = retained_run({"data": "dataset-reference/1"})
    with pytest.raises(WorkspaceError, match="contract"):
        publication.stage(principal, identity, 0, "data", "wrong-type/1", {})
    with pytest.raises(WorkspaceError, match="generation"):
        publication.publish(principal, identity, -1)
    principal, legacy = retained_run({})
    with pytest.raises(WorkspaceError, match="contract"):
        publication.publish(principal, legacy, 0)


def test_api_reads_committed_outputs_when_temporal_is_unavailable(retained_run, monkeypatch):
    from finai_api.api import workflow_routes
    from finai_api.config import get_settings
    from finai_api.main import app

    principal, identity = retained_run({"data": "dataset-reference/1"})
    publication.stage(principal, identity, 0, "data", "dataset-reference/1", {"id": "retained"})
    manifest = publication.publish(principal, identity, 0)
    # Staging a later generation must not expose it through the publication consumer API.
    publication.stage(principal, identity, 1, "data", "dataset-reference/1", {"id": "new"})
    monkeypatch.setenv(
        "FINAI_ACCESS_TOKENS",
        json.dumps({"publication-api-check": principal.model_dump(mode="json")}),
    )
    get_settings.cache_clear()

    async def offline():
        raise WorkspaceError(503, "Runtime offline")

    monkeypatch.setattr(workflow_routes, "client", offline)
    with TestClient(app) as client:
        response = client.get(
            f"/v1/workspace/workflows/{identity}",
            headers={"Authorization": "Bearer publication-api-check"},
        )
        assert response.status_code == 200
        assert response.json()["publications"] == [manifest]
        assert response.json()["runtime_status"] == "UNOBSERVABLE"
        assert client.get(f"/v1/workspace/workflows/{identity}").status_code == 401
