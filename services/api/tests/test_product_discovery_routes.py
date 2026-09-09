"""Product transport retains exact context and never starts rejected previews."""

from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from finai_api.api import transformation_routes
from finai_api.domain.authority import ExactScope
from finai_api.domain.review import Principal
from finai_api.main import app
from finai_api.security import authenticated_principal
from finai_api.services import (
    company_financial_results,
    transformation_preview,
    transformation_runs,
)
from finai_api.services.workspace import WorkspaceError


@pytest.fixture
def actor():
    principal = Principal(
        actor_id="product-operator",
        display_name="Operator",
        permissions=("ontology_read", "ingest"),
        scope=ExactScope(
            tenant_id=uuid4(), legal_entity_id=str(uuid4()), period="2025-01", currency="GEL"
        ),
    )
    app.dependency_overrides[authenticated_principal] = lambda: principal
    try:
        yield principal
    finally:
        app.dependency_overrides.pop(authenticated_principal, None)


def body():
    return {
        "request_id": str(uuid4()),
        "transformation": {"resource_id": str(uuid4()), "version_id": str(uuid4())},
        "valid_at": "2025-01-31T00:00:00.123456Z",
        "known_at": "2026-09-08T08:00:00.654321Z",
    }


def test_financial_discovery_preserves_company_clocks_and_independent_cursors(actor, monkeypatch):
    producer = Mock(return_value={"contract": "company-financial-results/1"})
    monkeypatch.setattr(company_financial_results, "discover", producer)
    company, function_cursor, invocation_cursor = uuid4(), uuid4(), uuid4()
    query = {
        "company_id": str(company),
        "valid_at": body()["valid_at"],
        "known_at": body()["known_at"],
        "after_function_id": str(function_cursor),
        "after_invocation_id": str(invocation_cursor),
    }
    response = TestClient(app).get("/v1/ontology/company-financial-results", params=query)
    assert response.status_code == 200
    args, kwargs = producer.call_args
    assert args == (actor, company)
    assert kwargs["valid_at"].microsecond == 123456
    assert kwargs["known_at"].microsecond == 654321
    assert kwargs["after_function_id"] == function_cursor
    assert kwargs["after_invocation_id"] == invocation_cursor


def test_preview_is_read_only_and_hash_mismatch_cannot_start_runtime(actor, monkeypatch):
    preview = Mock(return_value={"contract": "transformation-preview/1", "plan_hash": "a" * 64})
    retain = Mock(side_effect=WorkspaceError(409, "Reviewed plan changed"))
    runtime = AsyncMock(side_effect=AssertionError("A rejected plan must never start"))
    monkeypatch.setattr(transformation_preview, "preview", preview)
    monkeypatch.setattr(transformation_runs, "retain", retain)
    monkeypatch.setattr(transformation_routes, "client", runtime)
    request = body()
    client = TestClient(app)
    assert client.post("/v1/ontology/transformations/preview", json=request).status_code == 200
    retain.assert_not_called()
    response = client.post(
        "/v1/ontology/transformations/previewed-runs",
        json={
            "request": request,
            "expected_plan_hash": "a" * 64,
        },
    )
    assert response.status_code == 409
    assert retain.call_args.kwargs == {"expected_plan_hash": "a" * 64}
    assert str(retain.call_args.args[1].request_id) == request["request_id"]
    runtime.assert_not_called()


def test_new_routes_require_identity_before_any_producer(monkeypatch):
    denied = Mock(side_effect=AssertionError("Unauthenticated producer access"))
    monkeypatch.setattr(company_financial_results, "discover", denied)
    monkeypatch.setattr(transformation_preview, "preview", denied)
    monkeypatch.setattr(transformation_runs, "retain", denied)
    client = TestClient(app)
    assert (
        client.get(
            "/v1/ontology/company-financial-results", params={"company_id": str(uuid4())}
        ).status_code
        == 401
    )
    assert client.post("/v1/ontology/transformations/preview", json=body()).status_code == 401
    assert (
        client.post(
            "/v1/ontology/transformations/previewed-runs",
            json={"request": body(), "expected_plan_hash": "a" * 64},
        ).status_code
        == 401
    )
    denied.assert_not_called()
