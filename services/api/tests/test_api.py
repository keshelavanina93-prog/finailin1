from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from finai_api.main import app

client = TestClient(app, headers={"Authorization": "Bearer test-token"})


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_compile_endpoint(request_payload: Callable[..., dict[str, Any]]) -> None:
    response = client.post("/v1/hydration/compile", json=request_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["exact_scope"]["currency"] == "GEL"
    assert body["promotion_state"] == "CANDIDATE_ONLY"


def test_contract_rejects_invalid_scope(request_payload: Callable[..., dict[str, Any]]) -> None:
    payload = request_payload()
    payload["authority_contract"]["scope"]["currency"] = "gel"

    response = client.post("/v1/hydration/compile", json=payload)

    assert response.status_code == 422
