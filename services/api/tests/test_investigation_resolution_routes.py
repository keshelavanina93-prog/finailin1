"""Mounted resolution transport: exact request and denial before shared effect preparation."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from finai_api.domain.authority import ExactScope
from finai_api.domain.review import Principal
from finai_api.main import app
from finai_api.security import authenticated_principal
from finai_api.services import investigation_resolution as resolution


def body():
    def pin():
        return {"resource_id": str(uuid4()), "version_id": str(uuid4()), "content_hash": "a" * 64}

    return {"request_id": str(uuid4()), "finding": pin(), "investigation": pin(),
            "matched_exception_run_id": "fcr_" + "b" * 64,
            "rationale": "Resolve this source finding from reviewed matched evidence"}


@pytest.fixture
def principal():
    return Principal(actor_id="reader", display_name="Reader", permissions=("ontology_read",),
                     scope=ExactScope(tenant_id=uuid4(), legal_entity_id=str(uuid4()),
                                      period="2025-01", currency="GEL"))


def test_resolution_route_denies_before_preparing_effect(monkeypatch, principal):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Denied requests cannot prepare or publish resolutions")

    monkeypatch.setattr(resolution, "prepare", forbidden)
    client = TestClient(app)
    path = "/v1/ontology/operations/investigation-resolutions"
    assert client.post(path, json=body()).status_code == 401
    app.dependency_overrides[authenticated_principal] = lambda: principal
    try:
        assert client.post(path, json=body()).status_code == 403
    finally:
        app.dependency_overrides.pop(authenticated_principal, None)


def test_resolution_route_preserves_pins_and_rejects_extra_authority(monkeypatch, principal):
    seen = []

    def invoke(actor, request):
        assert actor == principal
        seen.append(request.model_dump(mode="json"))
        return {"request": seen[-1]}

    monkeypatch.setattr(resolution, "invoke", invoke)
    app.dependency_overrides[authenticated_principal] = lambda: principal
    try:
        client = TestClient(app)
        path = "/v1/ontology/operations/investigation-resolutions"
        request = body()
        assert client.post(path, json=request).json()["request"] == request
        for extra in ({"state": "RESOLVED"}, {"automatic_resolution": True},
                      {"company_id": str(uuid4())}, {"financial_impact": "731.97"}):
            assert client.post(path, json={**request, **extra}).status_code == 422
        bad = {**request, "finding": {**request["finding"], "content_hash": "unverified"}}
        assert client.post(path, json=bad).status_code == 422
        assert len(seen) == 1
    finally:
        app.dependency_overrides.pop(authenticated_principal, None)
