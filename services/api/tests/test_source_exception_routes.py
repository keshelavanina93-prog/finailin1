"""Mounted transport preserves exact exception inputs and denies access before storage."""

from uuid import uuid4

from fastapi.testclient import TestClient

from finai_api.domain.authority import ExactScope
from finai_api.domain.review import Principal
from finai_api.main import app
from finai_api.security import authenticated_principal
from finai_api.services import source_reconciliation_exception as exceptions


def request():
    return {
        "company_id": str(uuid4()),
        "invocation_id": str(uuid4()),
        "journal_snapshot_at": "2026-09-08T08:00:00.123456Z",
        "expected_reconciliation_receipt_hash": "b" * 64,
        "coordinate": "Base!S2",
    }


def test_exception_routes_deny_before_reconciliation_or_storage(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Denied requests must not reach source or persistence")

    monkeypatch.setattr(exceptions.journal_reconciliation, "reconcile", forbidden)
    monkeypatch.setattr(exceptions.fact_runs, "read_run", forbidden)
    monkeypatch.setattr(exceptions.fact_runs, "retain_run", forbidden)
    client = TestClient(app)
    path = "/v1/ontology/source-exceptions"
    run = "/fcr_" + "a" * 64
    for headers, status in [({}, 401), ({"Authorization": "Bearer test-token"}, 403)]:
        assert client.post(path, json=request(), headers=headers).status_code == status
        assert client.get(path + run, headers=headers).status_code == status


def test_exception_routes_preserve_inputs_and_refuse_caller_facts(monkeypatch):
    body = request()
    principal = Principal(
        actor_id="route-test",
        display_name="Route test",
        permissions=("ontology_read",),
        scope=ExactScope(
            tenant_id=uuid4(), legal_entity_id=body["company_id"], period="2025-01", currency="GEL"
        ),
    )
    seen = []

    def retain(actor, selected):
        assert actor == principal
        seen.append(selected)
        return {"request": selected.model_dump(mode="json")}

    monkeypatch.setattr(exceptions, "retain", retain)
    monkeypatch.setattr(exceptions, "read", lambda _actor, run_id: {"run_id": run_id})
    app.dependency_overrides[authenticated_principal] = lambda: principal
    client = TestClient(app)
    path = "/v1/ontology/source-exceptions"
    try:
        response = client.post(path, json=body)
        assert response.status_code == 200
        assert response.json()["request"] == body
        for extra in ({"amount": "20"}, {"finding_eligible": True}, {"financial_impact": "20"}):
            assert client.post(path, json={**body, **extra}).status_code == 422
        assert len(seen) == 1
        assert client.get(path + "/fcr_" + "a" * 64).status_code == 200
        assert client.get(path + "/current").status_code == 422
        assert client.get(path + "/fcr_" + "A" * 64).status_code == 422
    finally:
        app.dependency_overrides.pop(authenticated_principal, None)
