"""Native observation review and export preserve scope, history and original bytes."""

import json
import os
from hashlib import sha256
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from finai_api.config import get_settings
from finai_api.main import app


@pytest.mark.skipif(
    os.getenv("G8_BINDING_DB_TEST") != "1" or not os.getenv("FINAI_DATABASE_URL"),
    reason="Explicit disposable PostgreSQL acceptance opt-in required",
)
def test_scoped_observation_review_history_and_original_export(monkeypatch):
    scope = {
        "tenant_id": str(uuid4()), "legal_entity_id": "synthetic-evidence-journey",
        "period": "2026-08", "currency": "GEL",
    }
    maker = {
        "actor_id": "fixture-maker", "display_name": "Synthetic maker", "scope": scope,
        "permissions": ["read", "ingest", "review", "export"],
    }
    reviewer = {**maker, "actor_id": "fixture-checker"}
    observer = {**maker, "actor_id": "fixture-reader", "permissions": ["read"]}
    outsider = {**maker, "scope": {**scope, "period": "2026-07"}}
    monkeypatch.setenv("FINAI_ACCESS_TOKENS", json.dumps({
        "maker": maker, "checker": reviewer, "reader": observer, "outsider": outsider,
    }))
    get_settings.cache_clear()
    clients = {name: TestClient(app, headers={"Authorization": f"Bearer {name}"})
               for name in ("maker", "checker", "reader", "outsider")}
    client = clients["maker"]
    assert client.get("/v1/workspace/summary").json()["pending_count"] == 0

    def ingest(amount):
        source = f"account_code,debit,credit\n001,{amount},0\n002,0,{amount}\n"
        response = client.post("/v1/hydration/ingest", json={
            "scope": scope, "filename": "synthetic-observations.csv", "csv_text": source,
        })
        assert response.status_code == 200, response.text
        return response.json()["receipt_id"], source

    first, original = ingest("1.10")
    path = f"/v1/workspace/constructions/{first}"
    detail = client.get(path).json()
    assert detail["current_head"] is None and detail["decision"] is None
    assert detail["impact"]["added"] > 0
    decision = {"decision": "APPROVED", "reason": "Review synthetic source observations only",
                "idempotency_key": str(uuid4()), "expected_head": None}
    assert client.post(path + "/decision", json=decision).status_code == 403
    assert clients["reader"].post(path + "/decision", json=decision).status_code == 403
    approved = clients["checker"].post(path + "/decision", json=decision)
    assert approved.status_code == 200, approved.text
    assert clients["checker"].post(path + "/decision", json=decision).json() == approved.json()
    assert clients["checker"].post(path + "/decision", json={
        **decision, "reason": "Attempt to rewrite immutable review evidence",
    }).status_code == 409
    summary = client.get("/v1/workspace/summary").json()
    assert summary["approved_count"] == 1 and summary["pending_count"] == 0
    assert summary["active_versions"][0]["receipt_id"] == first
    assert client.get("/v1/workspace/intake", params={"state": "APPROVED"}).json()[0][
        "receipt_id"] == first
    objects = client.get("/v1/workspace/objects", params={"search": "001"}).json()
    assert objects and all(row["receipt_id"] == first for row in objects)
    obj_path = "/v1/workspace/objects/" + objects[0]["object_id"]
    observed = client.get(obj_path).json()
    assert observed["source_row_values"]["account_code"] == "001"
    assert observed["is_current"] is True
    preview = client.get(path + "/preview")
    assert preview.status_code == 200 and preview.headers["cache-control"] == "no-store"
    retained = client.get(path + "/source")
    assert retained.content == original.encode()
    assert retained.headers["x-content-sha256"] == sha256(original.encode()).hexdigest()
    exported = client.get(path + "/export")
    assert exported.json()["source_utf8"] == original
    assert exported.json()["certification"] == "NOT_CERTIFIED"
    assert exported.headers["x-content-sha256"] == sha256(exported.content).hexdigest()
    for suffix in ("/preview", "/source", "/export"):
        assert clients["reader"].get(path + suffix).status_code == 403
        assert clients["outsider"].get(path + suffix).status_code == 404
    assert clients["outsider"].get(obj_path).status_code == 404
    assert client.get("/v1/workspace/objects/missing").status_code == 404

    second, _ = ingest("2.20")
    next_path = f"/v1/workspace/constructions/{second}"
    changed = client.get(next_path).json()
    assert changed["current_head"] == first and changed["impact"]["changed"] > 0
    rejection = {"decision": "REJECTED", "reason": "Synthetic correction needs further review",
                 "idempotency_key": str(uuid4())}
    assert clients["checker"].post(next_path + "/decision", json=rejection).status_code == 200
    summary = client.get("/v1/workspace/summary").json()
    assert summary["rejected_count"] == 1 and summary["approved_count"] == 1
    assert summary["active_versions"][0]["receipt_id"] == first
    assert client.get(path + "/source").content == original.encode()
