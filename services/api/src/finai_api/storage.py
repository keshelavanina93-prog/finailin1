from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from finai_api.config import get_settings
from finai_api.domain.authority import ExactScope
from finai_api.domain.ingest import IngestReceipt, IngestRequest


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
        conn.execute(
            "INSERT INTO hydration_runs (tenant_id, receipt_id, exact_scope, source_bytes, "
            "source_sha256, request, receipt, submitted_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (tenant_id, receipt_id) DO NOTHING",
            (
                request.scope.tenant_id,
                receipt.receipt_id,
                Jsonb(request.scope.model_dump(mode="json")),
                request.csv_text.encode("utf-8"),
                receipt.source_sha256,
                Jsonb(request.model_dump(mode="json")),
                Jsonb(receipt.model_dump(mode="json")),
                actor_id,
            ),
        )
        row = conn.execute(
            "SELECT receipt FROM hydration_runs WHERE tenant_id=%s AND receipt_id=%s "
            "AND exact_scope=%s",
            (
                request.scope.tenant_id,
                receipt.receipt_id,
                Jsonb(request.scope.model_dump(mode="json")),
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("Receipt retention failed")
        return IngestReceipt.model_validate(row[0])


def retrieve(scope: ExactScope, receipt_id: str) -> IngestReceipt | None:
    with connection(scope) as conn:
        row = conn.execute(
            "SELECT receipt FROM hydration_runs WHERE tenant_id=%s AND receipt_id=%s "
            "AND exact_scope=%s",
            (scope.tenant_id, receipt_id, Jsonb(scope.model_dump(mode="json"))),
        ).fetchone()
        return IngestReceipt.model_validate(row[0]) if row else None
