"""Resolve existing retained artifacts without creating a second identity registry."""

import json
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from finai_api.domain.artifact_retention import ArtifactReference
from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services import execution_publication, fact_runs, report_workflows, source_documents
from finai_api.services.workspace import WorkspaceError
from finai_api.storage import connection, retained_source


def _metadata(principal: Principal, query: str, identity: str) -> dict[str, Any]:
    scope = principal.scope.model_dump(mode="json")
    with connection(principal.scope) as conn, conn.cursor(row_factory=dict_row) as cursor:
        conn.execute("SELECT set_config('finai.exact_scope',%s,true)", (json.dumps(scope),))
        row = cursor.execute(query, (principal.scope.tenant_id, identity, Jsonb(scope))).fetchone()
    if row is None:
        raise WorkspaceError(404, "Retained artifact unavailable in this exact scope")
    return dict(row)


def resolve_artifact(principal: Principal, reference: ArtifactReference) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    authority_scope = "SOURCE_OBSERVATION"
    if reference.kind == "SOURCE_RECEIPT":
        row = _metadata(
            principal,
            "SELECT exact_scope,source_storage,source_bytes,source_sha256,"
            "ingested_at AS recorded_at "
            "FROM hydration_runs WHERE tenant_id=%s AND receipt_id=%s AND exact_scope=%s",
            reference.receipt_id,
        )
        retained_source(principal.scope, row)
        artifact_class = "IMMUTABLE_SOURCE_EVIDENCE"
        content_hash = row["source_sha256"]
        recorded_at = row["recorded_at"].isoformat()
    elif reference.kind == "SOURCE_DOCUMENT":
        document, _ = source_documents.document_bytes(principal, reference.document_id)
        row = _metadata(
            principal,
            "SELECT created_at AS recorded_at FROM source_documents "
            "WHERE tenant_id=%s AND document_id=%s AND exact_scope=%s",
            reference.document_id,
        )
        artifact_class = "IMMUTABLE_SOURCE_EVIDENCE"
        content_hash = document["source_sha256"]
        recorded_at = row["recorded_at"].isoformat()
    elif reference.kind == "FACT_RUN":
        fact_runs.read_run(principal, reference.run_id)
        row = _metadata(
            principal,
            "SELECT created_at AS recorded_at FROM fact_calculation_runs "
            "WHERE tenant_id=%s AND run_id=%s AND exact_scope=%s",
            reference.run_id,
        )
        artifact_class = "REPRODUCIBLE_DERIVED_ARTIFACT"
        content_hash = reference.run_id.removeprefix("fcr_")
        recorded_at = row["recorded_at"].isoformat()
        authority_scope = "CALCULATION_EVIDENCE_ONLY"
    else:
        record = report_workflows.read(principal, reference.workflow_id)
        event = next(
            (
                event
                for event in record["events"]
                if event["event_id"] == f"publication:{reference.generation}"
            ),
            None,
        )
        manifest = event.get("manifest") if event else None
        if not event or event.get("state") != "PUBLISHED" or not isinstance(manifest, dict):
            raise WorkspaceError(404, "Published artifact unavailable in this exact scope")
        content_hash = execution_publication.digest(
            {key: value for key, value in manifest.items() if key != "publication_id"}
        )
        if (
            manifest.get("publication_id") != reference.publication_id
            or "pub_" + content_hash != reference.publication_id
            or manifest.get("workflow_id") != reference.workflow_id
            or manifest.get("generation") != reference.generation
            or manifest.get("authority") != "EXECUTION_ONLY"
            or manifest.get("definition_sha256")
            != execution_publication.digest(record["definition"])
        ):
            raise WorkspaceError(409, "Publication artifact does not match its retained contract")
        artifact_class = "AUTHORITATIVE_RECORD"
        authority_scope = "EXECUTION_ONLY"
        recorded_at = event["created_at"]
    return {
        "reference": reference.model_dump(mode="json"),
        "artifact_class": artifact_class,
        "content_hash": content_hash,
        "exact_scope": principal.scope.model_dump(mode="json"),
        "recorded_at": recorded_at,
        "authority_scope": authority_scope,
    }
