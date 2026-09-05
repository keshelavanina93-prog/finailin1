import json
import os
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from finai_api.config import get_settings
from finai_api.main import app


def payload() -> dict[str, object]:
    return {
        "scope": {
            "tenant_id": "805d8a32-d12b-4268-a236-b0b16e59da9f",
            "legal_entity_id": "entity-ge-001",
            "period": "2026-08",
            "currency": "GEL",
        },
        "filename": f"tb-{uuid4()}.csv",
        "csv_text": "account_code,debit,credit\n001,1.10,0\n002,0,1.10\n",
    }


def test_auth_denial_and_scope_omission() -> None:
    client = TestClient(app)
    assert client.post("/v1/hydration/ingest", json=payload()).status_code == 401
    client.headers["Authorization"] = "Bearer wrong"
    assert client.post("/v1/hydration/ingest", json=payload()).status_code == 401
    client.headers["Authorization"] = "Bearer test-token"
    data = payload()
    del data["scope"]
    assert client.post("/v1/hydration/ingest", json=data).status_code == 422


def test_scope_broadening_and_forbidden_objects() -> None:
    client = TestClient(app, headers={"Authorization": "Bearer test-token"})
    data = payload()
    data["scope"] = {**data["scope"], "legal_entity_id": "other"}
    assert client.post("/v1/hydration/ingest", json=data).status_code == 403
    data = payload()
    data["requested_objects"] = ["Invoice"]
    assert client.post("/v1/hydration/ingest", json=data).status_code == 403
    data["csv_text"] = "x,x\n1,2"
    assert client.post("/v1/hydration/ingest", json=data).status_code == 422


def test_missing_database_and_credentials_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINAI_DATABASE_URL", "")
    get_settings.cache_clear()
    client = TestClient(app, headers={"Authorization": "Bearer test-token"})
    assert client.post("/v1/hydration/ingest", json=payload()).status_code == 503
    assert client.get("/v1/hydration/receipts/missing").status_code == 503
    monkeypatch.setenv("FINAI_ACCESS_TOKENS", "{}")
    get_settings.cache_clear()
    assert client.post("/v1/hydration/ingest", json=payload()).status_code == 503


@pytest.mark.skipif(not os.getenv("FINAI_DATABASE_URL"), reason="PostgreSQL required")
def test_postgres_retention_replay_reconnect_and_scope_denial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(app, headers={"Authorization": "Bearer test-token"})
    data = payload()
    first = client.post("/v1/hydration/ingest", json=data)
    assert first.status_code == 200, first.text
    assert first.json() == client.post("/v1/hydration/ingest", json=data).json()
    receipt_id = first.json()["receipt_id"]
    new_client = TestClient(app, headers={"Authorization": "Bearer test-token"})
    assert new_client.get(f"/v1/hydration/receipts/{receipt_id}").json() == first.json()
    assert new_client.get("/v1/hydration/receipts/missing").status_code == 404
    # Same tenant, different legal entity must not see the receipt either.
    for change in ({"legal_entity_id": "other"}, {"tenant_id": str(uuid4())}):
        monkeypatch.setenv(
            "FINAI_ACCESS_TOKENS", json.dumps({"other": {**data["scope"], **change}})
        )
        get_settings.cache_clear()
        outsider = TestClient(app, headers={"Authorization": "Bearer other"})
        assert outsider.get(f"/v1/hydration/receipts/{receipt_id}").status_code == 404

    with psycopg.connect(os.environ["FINAI_DATABASE_URL"]) as conn:
        assert conn.execute(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user"
        ).fetchone() == (False, False)
        assert conn.execute("SELECT count(*) FROM hydration_runs").fetchone() == (0,)
        conn.execute(
            "SELECT set_config('finai.tenant_id', %s, true)", (data["scope"]["tenant_id"],)
        )
        row = conn.execute(
            "SELECT source_bytes, source_storage, request FROM hydration_runs WHERE receipt_id=%s",
            (receipt_id,),
        ).fetchone()
        assert row[0] is None
        assert row[1]["sha256"] == first.json()["source_sha256"]
        assert row[1]["byte_length"] == len(data["csv_text"].encode())
        assert "csv_text" not in row[2]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM hydration_runs WHERE receipt_id=%s", (receipt_id,))


@pytest.mark.skipif(
    not os.getenv("FINAI_MIGRATION_DATABASE_URL"), reason="Migration identity required"
)
def test_database_trigger_denies_evidence_mutation_even_for_owner() -> None:
    for statement in (
        "UPDATE hydration_runs SET receipt=receipt",
        "DELETE FROM hydration_runs",
        "TRUNCATE hydration_runs",
    ):
        with (
            psycopg.connect(os.environ["FINAI_MIGRATION_DATABASE_URL"]) as conn,
            pytest.raises(psycopg.errors.RaiseException, match="immutable"),
        ):
            conn.execute(statement)
