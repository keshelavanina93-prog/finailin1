"""Focused private object-store + PostgreSQL acceptance; leaves synthetic retained evidence."""

import json
import os
from hashlib import sha256
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from finai_api import evidence_objects, storage
from finai_api.api import routes
from finai_api.config import get_settings
from finai_api.domain.authority import ExactScope
from finai_api.domain.ingest import IngestRequest
from finai_api.domain.review import Principal
from finai_api.main import app
from finai_api.services.ingestion import compile_source


def test_readiness_object_outage_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable() -> None:
        raise evidence_objects.EvidenceStoreUnavailable("sensitive credential marker")

    monkeypatch.setattr(routes, "check_ready", unavailable)
    response = TestClient(app).get("/ready")
    assert response.status_code == 503
    assert response.json()["evidence_store"] == "unavailable"
    assert "sensitive" not in response.text


@pytest.mark.skipif(
    os.environ.get("G8_S3_DB_TEST") != "1", reason="Opt-in S3 and PostgreSQL acceptance"
)
def test_private_source_retention_reconnect_export_legacy_and_outage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = ExactScope(
        tenant_id=UUID("805d8a32-d12b-4268-a236-b0b16e59da9f"),
        legal_entity_id="synthetic-s3-" + uuid4().hex,
        period="2026-08",
        currency="GEL",
    )
    operator = Principal(
        actor_id="synthetic-s3-operator",
        display_name="Synthetic S3 operator",
        scope=scope,
        permissions=("read", "ingest", "review", "export"),
    )
    reviewer = operator.model_copy(update={"actor_id": "synthetic-s3-reviewer"})
    outsider = operator.model_copy(
        update={"scope": scope.model_copy(update={"legal_entity_id": "other"})}
    )
    monkeypatch.setenv(
        "FINAI_ACCESS_TOKENS",
        json.dumps(
            {
                "operator": operator.model_dump(mode="json"),
                "reviewer": reviewer.model_dump(mode="json"),
                "outsider": outsider.model_dump(mode="json"),
            }
        ),
    )
    get_settings.cache_clear()
    client = TestClient(app, headers={"Authorization": "Bearer operator"})
    assert client.get("/ready").status_code == 200
    request = IngestRequest(
        scope=scope,
        filename="SYNTHETIC-private-source.csv",
        csv_text="\ufeffaccount_code,debit,credit\r\n001,0.10,0\r\n002,0,0.10\r\n",
    )
    response = client.post("/v1/hydration/ingest", json=request.model_dump(mode="json"))
    assert response.status_code == 200, response.text
    receipt = response.json()
    metadata = receipt["source_storage"]
    assert metadata["backend"] == "S3" and metadata["version_id"]
    assert metadata["sha256"] == sha256(request.csv_text.encode()).hexdigest()
    assert (
        client.post("/v1/hydration/ingest", json=request.model_dump(mode="json")).json() == receipt
    )
    # Independent receipt for the same content shares exactly one scoped object/version.
    another = request.model_copy(update={"filename": "SYNTHETIC-second-source.csv"})
    second = client.post("/v1/hydration/ingest", json=another.model_dump(mode="json")).json()
    assert second["source_storage"] == metadata
    rid = receipt["receipt_id"]
    with storage.connection(scope) as conn, conn.cursor(row_factory=dict_row) as cursor:
        run = cursor.execute(
            "SELECT * FROM hydration_runs WHERE tenant_id=%s AND receipt_id=%s",
            (scope.tenant_id, rid),
        ).fetchone()
        assert run["source_bytes"] is None and "csv_text" not in run["request"]
        assert storage.retained_request(scope, run) == request
    restarted = TestClient(app, headers={"Authorization": "Bearer operator"})
    source = restarted.get(f"/v1/workspace/constructions/{rid}/source")
    assert source.content == request.csv_text.encode()
    assert source.headers["X-Content-SHA256"] == receipt["source_sha256"]
    exported = restarted.get(f"/v1/workspace/constructions/{rid}/export")
    assert exported.json()["source_utf8"] == request.csv_text
    assert exported.headers["X-Content-SHA256"] == sha256(exported.content).hexdigest()
    client.headers["Authorization"] = "Bearer reviewer"
    decision = {
        "decision": "APPROVED",
        "reason": "Independent synthetic object evidence review",
        "idempotency_key": str(uuid4()),
        "expected_head": None,
    }
    approved = client.post(f"/v1/workspace/constructions/{rid}/decision", json=decision)
    assert approved.status_code == 200, approved.text
    obj = client.get("/v1/workspace/objects").json()[0]
    assert (
        client.get(f"/v1/workspace/objects/{obj['object_id']}").json()["source_row_values"][
            "account_code"
        ]
        == "001"
    )
    client.headers["Authorization"] = "Bearer outsider"
    assert client.get(f"/v1/workspace/constructions/{rid}/source").status_code == 404
    # Legacy append-only bytea rows are deliberately still supported.
    legacy_request = request.model_copy(update={"filename": "SYNTHETIC-legacy-bytea.csv"})
    legacy = compile_source(legacy_request)
    with storage.connection(scope) as conn:
        conn.execute(
            "INSERT INTO hydration_runs (tenant_id,receipt_id,exact_scope,source_bytes,"
            "source_sha256,request,receipt,submitted_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                scope.tenant_id,
                legacy.receipt_id,
                Jsonb(scope.model_dump(mode="json")),
                legacy_request.csv_text.encode(),
                legacy.source_sha256,
                Jsonb(legacy_request.model_dump(mode="json")),
                Jsonb(legacy.model_dump(mode="json")),
                operator.actor_id,
            ),
        )

    # Simulated object loss is sanitized, cannot promote, and leaves no new receipt.
    def unavailable(*args: object, **kwargs: object) -> None:
        raise evidence_objects.EvidenceStoreUnavailable("sensitive storage marker")

    monkeypatch.setattr(evidence_objects, "read", unavailable)
    client.headers["Authorization"] = "Bearer reviewer"
    denied = client.post(
        f"/v1/workspace/constructions/{second['receipt_id']}/decision",
        json={**decision, "expected_head": rid, "idempotency_key": str(uuid4())},
    )
    assert denied.status_code == 503 and "sensitive" not in denied.text
    assert client.get(f"/v1/workspace/constructions/{rid}/source").status_code == 503
    assert (
        client.get(f"/v1/workspace/constructions/{legacy.receipt_id}/source").content
        == request.csv_text.encode()
    )
    monkeypatch.setattr(evidence_objects, "preserve", unavailable)
    client.headers["Authorization"] = "Bearer operator"
    missing = request.model_copy(update={"filename": "SYNTHETIC-failed-retention.csv"})
    assert (
        client.post("/v1/hydration/ingest", json=missing.model_dump(mode="json")).status_code == 503
    )
    assert storage.retrieve(scope, compile_source(missing).receipt_id) is None
    # SQL NULL must never satisfy object metadata integrity constraints.
    with storage.connection(scope) as conn, pytest.raises(psycopg.errors.CheckViolation):
        broken = {**metadata, "sha256": None}
        conn.execute(
            "INSERT INTO hydration_runs (tenant_id,receipt_id,exact_scope,source_bytes,"
            "source_sha256,request,receipt,submitted_by,source_storage) "
            "VALUES (%s,%s,%s,NULL,%s,%s,%s,%s,%s)",
            (
                scope.tenant_id,
                "synthetic-null-" + uuid4().hex,
                Jsonb(scope.model_dump(mode="json")),
                receipt["source_sha256"],
                Jsonb(request.model_dump(mode="json", exclude={"csv_text"})),
                Jsonb({**receipt, "source_storage": broken}),
                operator.actor_id,
                Jsonb(broken),
            ),
        )
