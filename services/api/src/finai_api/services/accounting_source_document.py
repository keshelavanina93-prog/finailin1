"""Read existing retained document or construction evidence without copying its registry."""

from typing import Any

from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services.source_documents import document_bytes
from finai_api.services.workspace import WorkspaceError, _run
from finai_api.storage import connection, retained_source


def read_source(principal: Principal, identity: str) -> tuple[dict[str, Any], bytes]:
    require_permission(principal, "ontology_read")
    if identity.startswith("doc_"):
        return document_bytes(principal, identity)
    if not identity.startswith("ir_"):
        raise WorkspaceError(422, "Select an existing retained document or construction receipt")
    with connection(principal.scope) as conn:
        run = _run(conn, principal, identity)
        content = retained_source(principal.scope, run)
    request, receipt = run["request"], run["receipt"]
    return {
        "document_id": identity,
        "construction_receipt_id": identity,
        "filename": request["filename"],
        "source_sha256": run["source_sha256"],
        "storage": run.get("source_storage"),
        "source_snapshot": {
            "kind": "RETAINED_CONSTRUCTION_SOURCE",
            "receipt_id": identity,
            "exact_scope": run["exact_scope"],
            "source_use": request.get("source_use"),
            "source_encoding": request.get("source_encoding"),
            "inspection_version": request.get("inspection_version"),
            "source_class": receipt.get("source_class"),
            "source_profile": receipt.get("source_profile", {}),
            "ingested_at": run["ingested_at"],
        },
    }, content
