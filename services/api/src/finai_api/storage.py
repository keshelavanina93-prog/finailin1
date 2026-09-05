from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from finai_api import evidence_objects
from finai_api.config import get_settings
from finai_api.domain.authority import ExactScope
from finai_api.domain.ingest import IngestReceipt, IngestRequest, SourceStorage


@contextmanager
def connection(scope: ExactScope) -> Iterator[psycopg.Connection[Any]]:
    dsn = get_settings().database_url.get_secret_value()
    if not dsn:
        raise RuntimeError("Database is not configured")
    with psycopg.connect(dsn, connect_timeout=3) as conn:
        conn.execute("SELECT set_config('finai.tenant_id', %s, true)", (str(scope.tenant_id),))
        yield conn


def retain(
    request: IngestRequest, receipt: IngestReceipt, actor_id: str | None = None
) -> IngestReceipt:
    with connection(request.scope) as conn:
        # Replays return retained metadata, including its original object version/bucket.
        existing = conn.execute(
            "SELECT receipt FROM hydration_runs WHERE tenant_id=%s "
            "AND receipt_id=%s AND exact_scope=%s",
            (
                request.scope.tenant_id,
                receipt.receipt_id,
                Jsonb(request.scope.model_dump(mode="json")),
            ),
        ).fetchone()
        if existing:
            return IngestReceipt.model_validate(existing[0])
        metadata = evidence_objects.preserve(
            request.scope, request.csv_text.encode("utf-8"), receipt.source_sha256
        )
        stored = receipt.model_copy(update={"source_storage": metadata})
        conn.execute(
            "INSERT INTO hydration_runs (tenant_id, receipt_id, exact_scope, source_bytes, "
            "source_sha256, request, receipt, submitted_by, source_storage) "
            "VALUES (%s,%s,%s,NULL,%s,%s,%s,%s,%s) ON CONFLICT (tenant_id, receipt_id) DO NOTHING",
            (
                request.scope.tenant_id,
                receipt.receipt_id,
                Jsonb(request.scope.model_dump(mode="json")),
                receipt.source_sha256,
                Jsonb(request.model_dump(mode="json", exclude={"csv_text"})),
                Jsonb(stored.model_dump(mode="json")),
                actor_id,
                Jsonb(metadata.model_dump(mode="json")),
            ),
        )
        row = conn.execute(
            "SELECT receipt FROM hydration_runs WHERE tenant_id=%s "
            "AND receipt_id=%s AND exact_scope=%s",
            (
                request.scope.tenant_id,
                receipt.receipt_id,
                Jsonb(request.scope.model_dump(mode="json")),
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("Receipt retention failed")
        return IngestReceipt.model_validate(row[0])


def retained_source(scope: ExactScope, run: dict[str, Any]) -> bytes:
    if run["exact_scope"] != scope.model_dump(mode="json"):
        raise evidence_objects.EvidenceStoreUnavailable("Retained source scope verification failed")
    if run.get("source_storage") is not None:
        metadata = SourceStorage.model_validate(run["source_storage"])
        if metadata.sha256 != run["source_sha256"]:
            raise evidence_objects.EvidenceStoreUnavailable(
                "Retained source metadata verification failed"
            )
        return evidence_objects.read(scope, metadata)
    content = bytes(run["source_bytes"])
    if sha256(content).hexdigest() != run["source_sha256"]:
        raise evidence_objects.EvidenceStoreUnavailable(
            "Retained source integrity verification failed"
        )
    return content


def retained_request(scope: ExactScope, run: dict[str, Any]) -> IngestRequest:
    # Reconstruction is transient; raw bytes are not duplicated into PostgreSQL request JSON.
    return IngestRequest.model_validate(
        {**run["request"], "csv_text": retained_source(scope, run).decode("utf-8")}
    )


def retrieve(scope: ExactScope, receipt_id: str) -> IngestReceipt | None:
    with connection(scope) as conn:
        row = conn.execute(
            "SELECT receipt FROM hydration_runs WHERE tenant_id=%s AND receipt_id=%s "
            "AND exact_scope=%s",
            (scope.tenant_id, receipt_id, Jsonb(scope.model_dump(mode="json"))),
        ).fetchone()
        return IngestReceipt.model_validate(row[0]) if row else None
