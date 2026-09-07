"""Read-only retained worksheet adapter; cell coordinates are not canonical object IDs."""

import json

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from finai_api.domain.function_execution import (
    FunctionDefinition,
    FunctionInvocation,
    WorksheetImplementation,
)
from finai_api.domain.review import Principal
from finai_api.services.source_document_preview import preview
from finai_api.services.source_documents import document_bytes
from finai_api.services.workspace import WorkspaceError
from finai_api.storage import connection


def source_plan(
    p: Principal, request: FunctionInvocation, spec: FunctionDefinition, pins: dict
) -> dict:
    adapter = spec.definition
    assert isinstance(adapter, WorksheetImplementation)
    if request.limit > 50 or request.offset + request.limit > adapter.row_count:
        raise WorkspaceError(409, "Invocation page exceeds the reviewed worksheet window")
    evidence = pins.get(str(spec.evidence_id))
    if (
        evidence is None
        or evidence["object_type"] != "SourceEvidence"
        or evidence["attributes"].get("sha256") != adapter.source_sha256
    ):
        raise WorkspaceError(409, "Worksheet SourceEvidence exact hash pin is unavailable")
    if evidence["system_from"] > request.known_at:
        raise WorkspaceError(409, "Worksheet SourceEvidence was unavailable at the knowledge time")
    scope = p.scope.model_dump(mode="json")
    with connection(p.scope) as conn, conn.cursor(row_factory=dict_row) as c:
        c.execute("SELECT set_config('finai.exact_scope',%s,true)", (json.dumps(scope),))
        row = c.execute(
            "SELECT created_at FROM source_documents WHERE tenant_id=%s "
            "AND document_id=%s AND exact_scope=%s",
            (p.scope.tenant_id, adapter.document_id, Jsonb(scope)),
        ).fetchone()
    if row is None or row["created_at"] > request.known_at:
        raise WorkspaceError(
            409, "Retained worksheet was unavailable at the requested knowledge time"
        )
    metadata, _ = document_bytes(p, adapter.document_id)
    if metadata["source_sha256"] != adapter.source_sha256:
        raise WorkspaceError(409, "Retained worksheet differs from the reviewed source hash")
    return {
        "document_id": adapter.document_id,
        "sha256": adapter.source_sha256,
        "filename": metadata["filename"],
        "sheet": adapter.sheet,
        "first_row": adapter.first_row,
        "row_count": adapter.row_count,
        "evidence": {
            "resource_id": str(evidence["resource_id"]),
            "version_id": str(evidence["version_id"]),
            "content_hash": evidence["content_hash"],
        },
    }


def execute(p: Principal, request: FunctionInvocation, plan: dict) -> dict:
    source = plan["source_document"]
    result = preview(
        p,
        source["document_id"],
        source["sheet"],
        source["first_row"] + request.offset,
        request.limit,
    )
    if result["sha256"] != source["sha256"]:
        raise WorkspaceError(409, "Worksheet result failed source hash verification")
    next_offset: int | None = request.offset + request.limit
    if next_offset >= source["row_count"] or result["next_offset"] is None:
        next_offset = None
    return {
        "contract": "function-result/1",
        "function": plan["function"],
        "implementation": plan["implementation"],
        "plan_hash": plan["plan_hash"],
        "source_document": source,
        "source_rows": result["rows"],
        "returned_rows": len(result["rows"]),
        "next_offset": next_offset,
        "objects": [],
        "derived_values": [],
        "used_versions": [],
        "static_dependencies": plan["static_dependencies"],
        "query": {
            "valid_at": request.valid_at.isoformat(),
            "known_at": request.known_at.isoformat(),
            "offset": request.offset,
            "limit": request.limit,
        },
        "source_query": {
            key: result[key]
            for key in ("offset", "row_count", "column_count", "date_mode", "next_offset")
        },
        "coverage": "REVIEWED_WORKSHEET_PAGE_ONLY",
        "temporal_semantics": "IMMUTABLE_RETAINED_SNAPSHOT_NOT_VALID_TIME_FACTS",
        "authority": "SOURCE_CELLS_ONLY",
        "mode": "EVIDENCE_ANALYSIS_ONLY",
        "business_effect_authorized": False,
        "current_use_authorized": False,
    }
