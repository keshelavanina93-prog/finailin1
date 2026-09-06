"""Retain original documents independently from tabular accounting interpretation."""

import json
from hashlib import sha256

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from finai_api import evidence_objects
from finai_api.domain.ingest import SourceStorage
from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services.workspace import WorkspaceError
from finai_api.storage import connection


def retain_document(principal: Principal, filename: str, content: bytes) -> dict:
    require_permission(principal, "ingest")
    if not 0 < len(content) <= 32_000_000:
        raise WorkspaceError(413, "Retained documents must be between 1 byte and 32 MB")
    if not filename.strip() or len(filename) > 256:
        raise WorkspaceError(422, "A document name of 1-256 characters is required")
    scope = principal.scope.model_dump(mode="json")
    digest = sha256(content).hexdigest()
    identity = "doc_" + sha256(json.dumps([scope, digest], sort_keys=True).encode()).hexdigest()
    with connection(principal.scope) as conn:
        conn.execute("SELECT set_config('finai.exact_scope',%s,true)", (json.dumps(scope),))
        existing = conn.execute(
            "SELECT storage,filename FROM source_documents WHERE tenant_id=%s AND document_id=%s",
            (principal.scope.tenant_id, identity),
        ).fetchone()
        if existing:
            storage, filename = SourceStorage.model_validate(existing[0]), existing[1]
            evidence_objects.read(principal.scope, storage)
        else:
            storage = evidence_objects.preserve(
                principal.scope, content, digest, content_type="application/octet-stream"
            )
            conn.execute(
                "INSERT INTO source_documents"
                "(tenant_id,document_id,exact_scope,source_sha256,filename,storage,actor_id) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (
                    principal.scope.tenant_id,
                    identity,
                    Jsonb(scope),
                    digest,
                    filename,
                    Jsonb(storage.model_dump(mode="json")),
                    principal.actor_id,
                ),
            )
            filename = conn.execute(
                "SELECT filename FROM source_documents WHERE tenant_id=%s AND document_id=%s",
                (principal.scope.tenant_id, identity),
            ).fetchone()[0]
    return {
        "document_id": identity,
        "filename": filename,
        "sha256": digest,
        "byte_length": storage.byte_length,
        "state": "RETAINED_UNINTERPRETED",
    }


def document_bytes(principal: Principal, identity: str) -> tuple[dict, bytes]:
    require_permission(principal, "ontology_read")
    with connection(principal.scope) as conn, conn.cursor(row_factory=dict_row) as cursor:
        scope = principal.scope.model_dump(mode="json")
        conn.execute("SELECT set_config('finai.exact_scope',%s,true)", (json.dumps(scope),))
        row = cursor.execute(
            "SELECT document_id,filename,source_sha256,storage FROM source_documents "
            "WHERE tenant_id=%s AND document_id=%s AND exact_scope=%s",
            (principal.scope.tenant_id, identity, Jsonb(scope)),
        ).fetchone()
    if not row:
        raise WorkspaceError(404, "Retained document unavailable in this source scope")
    return row, evidence_objects.read(principal.scope, SourceStorage.model_validate(row["storage"]))


def list_documents(principal: Principal, offset: int = 0) -> list[dict]:
    require_permission(principal, "ontology_read")
    with connection(principal.scope) as conn, conn.cursor(row_factory=dict_row) as cursor:
        scope = principal.scope.model_dump(mode="json")
        conn.execute("SELECT set_config('finai.exact_scope',%s,true)", (json.dumps(scope),))
        return cursor.execute(
            "SELECT document_id,filename,source_sha256 AS sha256,"
            "(storage->>'byte_length')::bigint AS byte_length,created_at FROM source_documents "
            "WHERE tenant_id=%s AND exact_scope=%s "
            "ORDER BY created_at,document_id LIMIT 100 OFFSET %s",
            (principal.scope.tenant_id, Jsonb(scope), offset),
        ).fetchall()
