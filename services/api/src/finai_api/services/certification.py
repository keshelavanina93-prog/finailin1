"""Retained structural evidence with separately rechecked current-use authorization.

The only evaluator is the existing canonical promotion evaluator. Its receipt certifies
definition conformance to a declared contract, never accounting or source authenticity.
"""

import json
from collections.abc import Callable
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid5

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from finai_api.domain.authority import canonical_sha256
from finai_api.domain.certification import CertificationContract, CertificationEvaluationRequest
from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services.proposal_evaluation import require_evaluation
from finai_api.services.resources import resource_connection
from finai_api.services.upstream_authority import upstream_authority
from finai_api.services.workspace import WorkspaceError


def validate_contract(item: ResourceMutation, target: Callable[[str, str, str], dict]) -> None:
    contract = CertificationContract.model_validate(item.attributes)
    if contract.subject_schema_id:
        schema = target(
            str(contract.subject_schema_id), str(item.resource_id), "CERTIFICATION_SUBJECT_SCHEMA"
        )
        if (
            schema["object_type"] != "SchemaDefinition"
            or schema["identity_key"] != contract.definition.subject_type
            or schema["authority_state"] != "APPROVED"
        ):
            raise WorkspaceError(
                409, "Certification subject schema does not match its declared type"
            )


def _digest(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _current(
    c: Any, p: Principal, ref: VersionReference, allow_unavailable: bool = False
) -> dict[str, Any]:
    # Local import avoids a lifecycle/certification module cycle during integration.
    from finai_api.services.resource_lifecycle import _latest, _version

    resource = _version(c, p, ref)
    event = _latest(c, p, ref.version_id)
    if event and (
        event["payload"]["target_state"] in ("REVOKED", "SUPERSEDED")
        or (not allow_unavailable and event["payload"]["availability_state"] != "AVAILABLE")
    ):
        raise WorkspaceError(409, "Certification input authority or availability was withdrawn")
    return resource


def _proof(
    c: Any,
    p: Principal,
    request: CertificationEvaluationRequest,
    allow_subject_unavailable: bool = False,
) -> dict[str, Any]:
    subject = _current(c, p, request.subject, allow_subject_unavailable)
    contract = _current(c, p, request.contract)
    if contract["object_type"] != "CertificationContract":
        raise WorkspaceError(409, "An exact canonical CertificationContract is required")
    spec = CertificationContract.model_validate(contract["attributes"])
    if subject["object_type"] != spec.definition.subject_type:
        raise WorkspaceError(409, "Subject type does not match the certification contract")
    if subject["access_entity"] != "__TENANT__" and contract["access_entity"] not in (
        subject["access_entity"],
        "__PLATFORM__",
    ):
        raise WorkspaceError(
            409, "Certification contract does not inherit the subject policy boundary"
        )
    schema_pin = None
    if spec.subject_schema_id:
        pin = c.execute(
            "SELECT DISTINCT target_version_id FROM resource_dependencies WHERE tenant_id=%s "
            "AND version_id=%s AND target_resource_id=%s",
            (p.scope.tenant_id, request.contract.version_id, spec.subject_schema_id),
        ).fetchall()
        if len(pin) != 1 or pin[0]["target_version_id"] != subject["schema_version_id"]:
            raise WorkspaceError(
                409, "Subject schema version does not match the retained contract pin"
            )
        schema_pin = {
            "resource_id": str(spec.subject_schema_id),
            "version_id": str(pin[0]["target_version_id"]),
        }
    row = c.execute(
        "SELECT p.* FROM resource_proposals p JOIN resource_decisions d "
        "USING(tenant_id,proposal_id) WHERE p.tenant_id=%s AND p.proposal_id=%s "
        "AND d.decision='APPROVED'",
        (p.scope.tenant_id, subject["proposal_id"]),
    ).fetchone()
    if row is None:
        raise WorkspaceError(409, "Subject has no retained accepted promotion evaluation")
    proposal = ResourceProposal.model_validate(row["payload"]["request"])
    validation = row["payload"]["validation"]
    require_evaluation(proposal, validation)
    mutation = next(
        (item for item in proposal.mutations if item.resource_id == request.subject.resource_id),
        None,
    )
    if (
        mutation is None
        or canonical_sha256(mutation) != subject["content_hash"]
        or uuid5(proposal.proposal_id, str(mutation.resource_id)) != request.subject.version_id
    ):
        raise WorkspaceError(409, "Promotion evaluation is not bound to this exact subject version")
    evaluation = validation["evaluation"]
    if not set(spec.definition.required_checks).issubset(evaluation["checks"]):
        raise WorkspaceError(409, "Retained evaluator does not satisfy the declared checks")
    subject_upstream = upstream_authority(
        c, p.scope.tenant_id, request.subject.version_id, check_certification=False
    )
    contract_upstream = upstream_authority(
        c, p.scope.tenant_id, request.contract.version_id, check_certification=False
    )
    if subject["access_entity"] != "__TENANT__" and any(
        ancestor["access_entity"] not in (subject["access_entity"], "__PLATFORM__")
        for ancestor in subject_upstream + contract_upstream
    ):
        raise WorkspaceError(409, "Certification lineage crosses the subject policy boundary")
    return {
        "purpose": "CANONICAL_DEFINITION_CONFORMANCE",
        "evaluator": spec.definition.evaluator,
        "status": "PASS",
        "subject": request.subject.model_dump(mode="json"),
        "contract": request.contract.model_dump(mode="json"),
        "subject_content_hash": subject["content_hash"],
        "contract_content_hash": contract["content_hash"],
        "access_entity": subject["access_entity"],
        "contract_attributes": contract["attributes"],
        "subject_schema": schema_pin,
        "promotion_proposal_id": str(proposal.proposal_id),
        "promotion_evaluation": evaluation,
        "subject_upstream": subject_upstream,
        "contract_upstream": contract_upstream,
    }


def _envelope(row: Any) -> dict[str, Any]:
    if _digest(row["payload"]) != row["proof_hash"]:
        raise WorkspaceError(409, "Retained certification proof integrity failed")
    return {
        "receipt_id": str(row["receipt_id"]),
        "proof_hash": row["proof_hash"],
        "proof": row["payload"],
        "recorded_at": row["recorded_at"].isoformat(),
        "current_use_authorized": False,
    }


def evaluate(p: Principal, request: CertificationEvaluationRequest) -> dict[str, Any]:
    require_permission(p, "ontology_read")
    with resource_connection(p) as conn, conn.cursor(row_factory=dict_row) as c:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (f"canonical:{p.scope.tenant_id}",),
        )
        existing = c.execute(
            "SELECT * FROM certification_receipts WHERE tenant_id=%s AND receipt_id=%s",
            (p.scope.tenant_id, request.request_id),
        ).fetchone()
        request_hash = canonical_sha256(request)
        if existing:
            if existing["request_hash"] != request_hash or existing["actor_id"] != p.actor_id:
                raise WorkspaceError(
                    409, "Certification request identity was already used differently"
                )
            return _envelope(existing)
        proof = _proof(c, p, request)
        row = c.execute(
            "INSERT INTO certification_receipts(tenant_id,receipt_id,access_entity,actor_id,"
            "request_hash,subject_resource_id,subject_version_id,contract_resource_id,"
            "contract_version_id,proof_hash,payload) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "RETURNING *",
            (
                p.scope.tenant_id,
                request.request_id,
                proof["access_entity"],
                p.actor_id,
                request_hash,
                request.subject.resource_id,
                request.subject.version_id,
                request.contract.resource_id,
                request.contract.version_id,
                _digest(proof),
                Jsonb(proof),
            ),
        ).fetchone()
        return _envelope(row)


def history(p: Principal, receipt_id: UUID) -> dict[str, Any]:
    require_permission(p, "ontology_read")
    with resource_connection(p) as conn, conn.cursor(row_factory=dict_row) as c:
        row = c.execute(
            "SELECT * FROM certification_receipts WHERE tenant_id=%s AND receipt_id=%s",
            (p.scope.tenant_id, receipt_id),
        ).fetchone()
        if row is None:
            raise WorkspaceError(404, "Certification receipt unavailable in authorized context")
        return _envelope(row)


def receipt_for_current_use(
    c: Any,
    p: Principal,
    receipt_id: UUID,
    subject: VersionReference,
    contract: VersionReference | None = None,
    *,
    allow_subject_unavailable: bool = False,
) -> dict[str, Any]:
    row = c.execute(
        "SELECT * FROM certification_receipts WHERE tenant_id=%s AND receipt_id=%s",
        (p.scope.tenant_id, receipt_id),
    ).fetchone()
    if row is None:
        raise WorkspaceError(404, "Certification receipt unavailable in authorized context")
    envelope = _envelope(row)
    proof = envelope["proof"]
    if proof["subject"] != subject.model_dump(mode="json") or (
        contract is not None and proof["contract"] != contract.model_dump(mode="json")
    ):
        raise WorkspaceError(409, "Certification receipt does not match the required exact pins")
    current = _proof(
        c,
        p,
        CertificationEvaluationRequest(
            request_id=receipt_id,
            subject=subject,
            contract=VersionReference.model_validate(proof["contract"]),
        ),
        allow_subject_unavailable=allow_subject_unavailable,
    )
    # Lifecycle events may advance legitimately. Current checks above validate them;
    # retained event observations remain historical evidence, not required current IDs.
    stable = set(proof) - {"subject_upstream", "contract_upstream"}
    if any(current.get(key) != proof[key] for key in stable):
        raise WorkspaceError(409, "Certification proof no longer matches canonical evidence")
    return {**envelope, "current_use_authorized": True}
