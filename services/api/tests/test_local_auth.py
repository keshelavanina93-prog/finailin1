import json

from fastapi.testclient import TestClient

from finai_api.config import get_settings
from finai_api.main import app


def test_local_login_exchanges_stable_credentials(monkeypatch):
    token = "local-token"
    scope = {
        "tenant_id": "805d8a32-d12b-4268-a236-b0b16e59da9f",
        "legal_entity_id": "entity-ge-001",
        "period": "2026-08",
        "currency": "GEL",
    }
    monkeypatch.setenv("FINAI_ENVIRONMENT", "local")
    monkeypatch.setenv("FINAI_DEV_LOGIN_ENABLED", "true")
    monkeypatch.setenv("FINAI_DEV_USERNAME", "nyxcore.local")
    monkeypatch.setenv("FINAI_DEV_PASSWORD", "NYXcore-local-2026!")
    monkeypatch.setenv("FINAI_DEV_ACCESS_TOKEN", token)
    monkeypatch.setenv("FINAI_ACCESS_TOKENS", json.dumps({token: scope}))
    get_settings.cache_clear()
    try:
        response = TestClient(app).post(
            "/v1/auth/local-login",
            json={"username": "nyxcore.local", "password": "NYXcore-local-2026!"},
        )
        assert response.status_code == 200
        assert response.json()["access_token"] == token
        assert response.json()["principal"]["scope"] == scope
    finally:
        get_settings.cache_clear()


def test_local_login_rejects_wrong_password(monkeypatch):
    monkeypatch.setenv("FINAI_ENVIRONMENT", "local")
    monkeypatch.setenv("FINAI_DEV_LOGIN_ENABLED", "true")
    monkeypatch.setenv("FINAI_DEV_USERNAME", "nyxcore.local")
    monkeypatch.setenv("FINAI_DEV_PASSWORD", "NYXcore-local-2026!")
    monkeypatch.setenv("FINAI_DEV_ACCESS_TOKEN", "local-token")
    monkeypatch.setenv("FINAI_ACCESS_TOKENS", json.dumps({"local-token": {
        "tenant_id": "805d8a32-d12b-4268-a236-b0b16e59da9f",
        "legal_entity_id": "entity-ge-001",
        "period": "2026-08",
        "currency": "GEL",
    }}))
    get_settings.cache_clear()
    try:
        response = TestClient(app).post(
            "/v1/auth/local-login",
            json={"username": "nyxcore.local", "password": "wrong"},
        )
        assert response.status_code == 401
    finally:
        get_settings.cache_clear()
