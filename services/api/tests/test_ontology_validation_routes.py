"""Transport failures preserve durable validation intent and cancellation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from finai_api.api import ontology_validation_routes as routes
from finai_api.domain.authority import ExactScope
from finai_api.domain.review import Principal
from finai_api.main import app
from finai_api.security import authenticated_principal


@pytest.fixture
def operator():
    principal = Principal(
        actor_id="validation-operator",
        display_name="Validation operator",
        scope=ExactScope(
            tenant_id=uuid4(),
            legal_entity_id="validation-company",
            period="2026-09",
            currency="GEL",
        ),
        permissions=["read", "ingest", "ontology_read"],
    )
    app.dependency_overrides[authenticated_principal] = lambda: principal
    try:
        yield principal
    finally:
        app.dependency_overrides.pop(authenticated_principal, None)


def request_payload():
    def pin():
        return {"resource_id": str(uuid4()), "version_id": str(uuid4()), "content_hash": "a" * 64}

    return {
        "request_id": str(uuid4()),
        "constraint_profile": pin(),
        "data": {"release": pin(), "graph_iris": ["urn:validation:data"]},
    }


def test_runtime_outage_returns_retained_identity_and_exact_redispatch(operator, monkeypatch):
    retained = []

    def retain(principal, request):
        assert principal == operator
        retained.append(request.model_dump(mode="json"))
        return "ontology-validation:" + str(request.request_id)

    monkeypatch.setattr(routes.ontology_validation_runs, "retain", retain)
    monkeypatch.setattr(
        routes, "client", AsyncMock(side_effect=RuntimeError("private runtime error"))
    )
    payload = request_payload()
    with TestClient(app) as client:
        first = client.post("/v1/ontology/external/validation/runs", json=payload)
        retry = client.post("/v1/ontology/external/validation/runs", json=payload)
    assert first.status_code == retry.status_code == 202
    assert first.json() == retry.json()
    assert first.json()["workflow_id"] == "ontology-validation:" + payload["request_id"]
    assert first.json()["state"] == "RETAINED_DISPATCH_UNOBSERVABLE"
    assert first.json()["automatic_outbox_dispatch"] is False
    assert first.json()["business_effect_authorized"] is False
    assert "private runtime error" not in first.text
    assert retained == [payload, payload]


def test_unobservable_runtime_preserves_retained_validation_outcome(operator, monkeypatch):
    request_id = uuid4()
    retained = {"state": "PUBLISHED", "terminal": {"outcome": "VIOLATES"}}
    monkeypatch.setattr(routes.ontology_validation_runs, "read", lambda *_: dict(retained))
    monkeypatch.setattr(routes, "client", AsyncMock(side_effect=RuntimeError("offline")))
    with TestClient(app) as client:
        response = client.get(f"/v1/ontology/external/validation/runs/{request_id}")
    assert response.status_code == 200
    assert response.json() == {**retained, "runtime_status": "UNOBSERVABLE"}


def test_cancellation_is_retained_before_runtime_notification(operator, monkeypatch):
    order = []

    def cancel(*_):
        order.append("retained")
        return {"state": "CANCELLED"}

    async def unavailable():
        order.append("notification")
        raise RuntimeError("offline")

    monkeypatch.setattr(routes.ontology_validation_runs, "cancel", cancel)
    monkeypatch.setattr(routes, "client", unavailable)
    with TestClient(app) as client:
        response = client.post(
            f"/v1/ontology/external/validation/runs/{uuid4()}/cancel",
            json={"command_id": str(uuid4()), "reason": "Operator cancelled this validation"},
        )
    assert response.status_code == 200
    assert order == ["retained", "notification"]
    assert response.json()["cancellation"]["state"] == "CANCELLED"
    assert response.json()["runtime_notified"] is False


def test_runtime_identity_is_distinct_across_every_scope_axis_and_actor(operator):
    identity = "ontology-validation:" + str(uuid4())
    baseline = routes.runtime_id(operator, identity)
    assert routes.runtime_id(operator.model_copy(), identity) == baseline
    variants = [operator.model_copy(update={"actor_id": "another-validation-operator"})]
    for field, value in {
        "tenant_id": uuid4(),
        "legal_entity_id": "another-company",
        "period": "2026-08",
        "currency": "USD",
    }.items():
        variants.append(
            operator.model_copy(update={"scope": operator.scope.model_copy(update={field: value})})
        )
    derived = {routes.runtime_id(principal, identity) for principal in variants}
    assert len(derived) == len(variants) and baseline not in derived
    assert baseline.startswith("ontology-validation-runtime:")
    assert operator.actor_id not in baseline and operator.scope.legal_entity_id not in baseline
    assert routes.runtime_id(operator, "ontology-validation:" + str(uuid4())) != baseline


def test_start_read_cancel_use_only_scoped_runtime_handle(operator, monkeypatch):
    payload = request_payload()
    identity = "ontology-validation:" + payload["request_id"]
    expected = routes.runtime_id(operator, identity)
    handle = SimpleNamespace(
        describe=AsyncMock(return_value=SimpleNamespace(status=SimpleNamespace(name="RUNNING"))),
        query=AsyncMock(return_value={"state": "VALIDATING"}),
        cancel=AsyncMock(),
    )
    runtime = SimpleNamespace(
        start_workflow=AsyncMock(), get_workflow_handle=Mock(return_value=handle)
    )
    monkeypatch.setattr(routes, "client", AsyncMock(return_value=runtime))
    monkeypatch.setattr(routes.ontology_validation_runs, "retain", lambda *_: identity)
    monkeypatch.setattr(
        routes.ontology_validation_runs, "read", lambda *_: {"workflow_id": identity}
    )
    monkeypatch.setattr(
        routes.ontology_validation_runs,
        "cancel",
        lambda *_: {"workflow_id": identity, "state": "CANCELLED"},
    )
    with TestClient(app) as client:
        started = client.post("/v1/ontology/external/validation/runs", json=payload)
        read = client.get(f"/v1/ontology/external/validation/runs/{payload['request_id']}")
        cancelled = client.post(
            f"/v1/ontology/external/validation/runs/{payload['request_id']}/cancel",
            json={"command_id": str(uuid4()), "reason": "Cancel scoped synthetic run"},
        )
    assert started.status_code == 202 and read.status_code == cancelled.status_code == 200
    call = runtime.start_workflow.await_args
    assert call.kwargs["id"] == expected
    assert call.args[1] == {
        "workflow_id": identity,
        "actor_id": operator.actor_id,
        "scope": operator.scope.model_dump(mode="json"),
    }
    assert [call.args[0] for call in runtime.get_workflow_handle.call_args_list] == [
        expected,
        expected,
    ]
    assert read.json()["workflow_id"] == started.json()["workflow_id"] == identity
    assert cancelled.json()["cancellation"]["workflow_id"] == identity
    handle.cancel.assert_awaited_once()
