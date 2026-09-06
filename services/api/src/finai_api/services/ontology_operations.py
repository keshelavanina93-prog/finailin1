"""Durable local ontology actions using the shared workflow and proposal authorities."""

import json
from hashlib import sha256
from uuid import UUID, uuid4, uuid5

from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from finai_api.domain.object_sets import ObjectSetQuery
from finai_api.domain.resources import ResourceProposal
from finai_api.security import require_permission
from finai_api.services import licence_notices, ontology_definitions, report_workflows, resources
from finai_api.services.workspace import WorkspaceError


class BindingAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    binding_id: UUID
    binding_version_id: UUID
    query: ObjectSetQuery
    rationale: str = Field(min_length=10, max_length=2000)


class LicenceAction(licence_notices.NoticeSelection):
    request_id: UUID
    document_id: str = Field(pattern=r"^doc_[a-f0-9]{64}$")


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def recent(principal, document_id: str | None = None, binding_id: UUID | None = None):
    require_permission(principal, "ontology_read")
    if bool(document_id) == bool(binding_id):
        raise WorkspaceError(422, "Select one document or binding for operation history")
    with report_workflows.scope_connection(principal) as conn:
        scope = report_workflows.set_scope(conn, principal)
        rows = conn.execute(
            "SELECT workflow_id FROM workflow_requests WHERE tenant_id=%s AND exact_scope=%s "
            "AND definition_version='ontology-action/1' "
            "AND payload->'invocation'->>%s=%s ORDER BY created_at DESC LIMIT 20",
            (
                principal.scope.tenant_id,
                Jsonb(scope),
                "document_id" if document_id else "binding_id",
                document_id or str(binding_id),
            ),
        ).fetchall()
    return {"operations": [read(principal, row[0]) for row in rows]}


def read(principal, identity):
    require_permission(principal, "ontology_read")
    record = report_workflows.read(principal, identity)
    if record["definition"].get("version") != "ontology-action/1":
        raise WorkspaceError(404, "Ontology operation unavailable")
    prepared = ResourceProposal.model_validate(record["request"]["prepared_proposal"])
    # Resource detail enforces current authorized visibility of the shared effect.
    try:
        proposal = resources.proposal_detail(principal, prepared.proposal_id)
        state = (
            "PUBLISHED"
            if proposal.decision == "APPROVED"
            else (proposal.decision or "PENDING_REVIEW")
        )
        proposal_value = proposal.model_dump(mode="json")
    except WorkspaceError as exc:
        if exc.status != 404:
            raise
        state, proposal_value = "PREPARED", None
    return {
        "operation_id": identity,
        "state": state,
        "proposal": proposal_value,
        "definition": record["definition"],
        "events": record["events"],
        "prepared_proposal_id": str(prepared.proposal_id),
    }


def invoke(principal, request: BindingAction | LicenceAction):
    require_permission(principal, "ontology_read")
    require_permission(principal, "ontology_propose")
    scope = principal.scope.model_dump(mode="json")
    identity = "opa_" + digest([scope, principal.actor_id, str(request.request_id)])
    payload = request.model_dump(mode="json")
    request_hash = digest(payload)
    # Hold only the operation-specific lock. Preparation may use the registry writer lock.
    # Frozen preparation commits before the shared proposal effect is attempted.
    with report_workflows.scope_connection(principal) as conn:
        report_workflows.set_scope(conn, principal)
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (identity,))
        existing = conn.execute(
            "SELECT payload FROM workflow_requests WHERE tenant_id=%s AND workflow_id=%s "
            "AND exact_scope=%s",
            (principal.scope.tenant_id, identity, Jsonb(scope)),
        ).fetchone()
        if existing:
            if existing[0].get("request_hash") != request_hash:
                raise WorkspaceError(409, "Operation request ID was reused for different content")
        else:
            proposal_id = uuid5(principal.scope.tenant_id, identity)
            if isinstance(request, BindingAction):
                prepared = ontology_definitions.prepare_binding(
                    principal,
                    request.binding_id,
                    request.query,
                    request.rationale,
                    request.binding_version_id,
                    proposal_id,
                )
                contract = {
                    "kind": "OBJECT_BINDING",
                    "binding_id": str(request.binding_id),
                    "binding_version_id": str(request.binding_version_id),
                }
            else:
                selection = licence_notices.NoticeSelection(
                    company_id=request.company_id, rationale=request.rationale
                )
                prepared = licence_notices.prepare(principal, request.document_id, selection)
                prepared = prepared.model_copy(update={"proposal_id": proposal_id})
                contract = {"kind": "LICENCE_NOTICE_BINDING", "parser": "matsne-issuance/1"}
            frozen = {
                "request_hash": request_hash,
                "invocation": payload,
                "prepared_proposal": prepared.model_dump(mode="json"),
                "definition": {
                    "version": "ontology-action/1",
                    **contract,
                    "effect": "CANONICAL_RESOURCE_PROPOSAL",
                    "publication": "EXISTING_RESOURCE_REVIEW",
                },
            }
            conn.execute(
                "INSERT INTO workflow_requests(tenant_id,workflow_id,exact_scope,actor_id,"
                "definition_version,payload) VALUES(%s,%s,%s,%s,%s,%s)",
                (
                    principal.scope.tenant_id,
                    identity,
                    Jsonb(scope),
                    principal.actor_id,
                    "ontology-action/1",
                    Jsonb(frozen),
                ),
            )
    return resume(principal, identity)


def resume(principal, identity):
    require_permission(principal, "ontology_read")
    require_permission(principal, "ontology_propose")
    record = report_workflows.read(principal, identity)
    if record["definition"].get("version") != "ontology-action/1":
        raise WorkspaceError(404, "Ontology operation unavailable")
    proposal = ResourceProposal.model_validate(record["request"]["prepared_proposal"])
    attempt_id = str(uuid4())
    report_workflows.event(
        principal,
        identity,
        "attempt:" + attempt_id,
        {
            "state": "STARTED",
            "actor_id": principal.actor_id,
            "proposal_id": str(proposal.proposal_id),
        },
    )
    try:
        try:
            resources.proposal_detail(principal, proposal.proposal_id)
        except WorkspaceError as missing:
            if missing.status != 404:
                raise
            invocation = record["request"]["invocation"]
            if "binding_id" in invocation:
                current = resources.get_resource(principal, UUID(invocation["binding_id"]))[
                    "resource"
                ]
                if (
                    current["authority_state"] != "APPROVED"
                    or str(current["version_id"]) != invocation["binding_version_id"]
                ):
                    raise WorkspaceError(
                        409, "Binding version changed before effect; prepare a new action"
                    ) from missing
        # Reuses atomic validation/promotion; retry submits the identical frozen payload.
        result = resources.propose(principal, proposal)
        report_workflows.event(
            principal,
            identity,
            "proposal-receipt",
            {
                "state": "PROPOSAL_RETAINED",
                "proposal_id": str(result.proposal.proposal_id),
                "request_hash": digest(proposal.model_dump(mode="json")),
            },
        )
    except WorkspaceError as exc:
        report_workflows.event(
            principal,
            identity,
            "failed:" + attempt_id,
            {"state": "FAILED", "status": exc.status, "reason": str(exc)},
        )
        raise
    return read(principal, identity)
