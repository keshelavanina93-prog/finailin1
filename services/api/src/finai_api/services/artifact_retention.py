"""Immutable retention evaluation. This service has no disposition execution capability."""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from finai_api.domain.artifact_retention import (
    RetentionEvaluationRequest,
    RetentionHistoryRequest,
    RetentionPolicy,
)
from finai_api.domain.authority import canonical_sha256
from finai_api.domain.resources import ResourceMutation
from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services.certification import _current, _digest
from finai_api.services.resources import resource_connection
from finai_api.services.upstream_authority import upstream_authority
from finai_api.services.workspace import WorkspaceError


def validate_policy(item: ResourceMutation, target: Callable[[str, str, str], dict]) -> None:
    RetentionPolicy.model_validate(item.attributes)


def evaluate_conditions(
    artifact: dict,
    policy: RetentionPolicy | None,
    action: str,
    at: datetime,
    unavailable: bool = False,
) -> dict:
    """Policy conditions are evidence only; satisfaction never authorizes an effect."""
    reasons = []
    eligible_at = None
    if unavailable:
        reasons.append("POLICY_UNAVAILABLE_FOR_CURRENT_USE")
    elif policy is None:
        reasons.append("POLICY_NOT_ESTABLISHED")
    else:
        spec = policy.definition
        if artifact["artifact_class"] not in spec.artifact_classes:
            reasons.append("ARTIFACT_CLASS_OUTSIDE_POLICY")
        if spec.legal_basis_state != "DECLARED":
            reasons.append("LEGAL_BASIS_NOT_ESTABLISHED")
        if spec.legal_hold:
            reasons.append("LEGAL_HOLD_DECLARED")
        recorded = datetime.fromisoformat(artifact["recorded_at"])
        eligible_at = recorded + timedelta(days=spec.minimum_retention_days)
        if at < eligible_at:
            reasons.append("MINIMUM_RETENTION_NOT_ELAPSED")
    status = (
        "PRESERVED" if action == "PRESERVE" else ("BLOCKED" if reasons else "POLICY_CONDITIONS_MET")
    )
    return {
        "status": status,
        "reasons": reasons,
        "requested_action": action,
        "effective_disposition": "PRESERVE",
        "execution_authorized": False,
        "legal_compliance_established": False,
        "eligible_at": eligible_at.isoformat() if eligible_at else None,
    }


def _envelope(row: Any) -> dict:
    if _digest(row["payload"]) != row["proof_hash"]:
        raise WorkspaceError(409, "Retention evidence integrity failed")
    return {
        "evaluation_id": str(row["evaluation_id"]),
        "proof_hash": row["proof_hash"],
        "proof": row["payload"],
        "recorded_at": row["recorded_at"].isoformat(),
        "execution_authorized": False,
        "current_use_authorized": False,
    }


def evaluate(p: Principal, request: RetentionEvaluationRequest) -> dict:
    from finai_api.services.artifact_references import resolve_artifact

    require_permission(p, "ontology_read")
    scope = p.scope.model_dump(mode="json")
    with resource_connection(p) as conn, conn.cursor(row_factory=dict_row) as c:
        conn.execute("SELECT set_config('finai.exact_scope',%s,true)", (json.dumps(scope),))
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (f"canonical:{p.scope.tenant_id}",),
        )
        old = c.execute(
            "SELECT * FROM artifact_retention_evaluations "
            "WHERE tenant_id=%s AND evaluation_id=%s AND exact_scope=%s",
            (p.scope.tenant_id, request.request_id, Jsonb(scope)),
        ).fetchone()
        request_hash = canonical_sha256(request)
        if old:
            if old["request_hash"] != request_hash or old["actor_id"] != p.actor_id:
                raise WorkspaceError(409, "Retention request identity already used differently")
            return _envelope(old)
        artifact = resolve_artifact(p, request.artifact)
        if artifact["exact_scope"] != scope or artifact["reference"] != request.artifact.model_dump(
            mode="json"
        ):
            raise WorkspaceError(409, "Artifact resolver must preserve exact reference and scope")
        now = datetime.now(UTC)
        policy = None
        retained_policy = None
        unavailable = False
        if request.policy:
            try:
                row = _current(c, p, request.policy)
                if (
                    row["object_type"] != "RetentionPolicy"
                    or row["access_entity"] != p.scope.legal_entity_id
                ):
                    raise WorkspaceError(409, "Policy must belong to the artifact company context")
                policy = RetentionPolicy.model_validate(row["attributes"])
                upstream_authority(c, p.scope.tenant_id, request.policy.version_id)
                retained_policy = {
                    "reference": request.policy.model_dump(mode="json"),
                    "content_hash": row["content_hash"],
                    "attributes": row["attributes"],
                }
            except WorkspaceError as exc:
                if exc.status not in (404, 409):
                    raise
                unavailable = True
                policy = None
                retained_policy = None
        proof = {
            "contract_version": "artifact-retention/1",
            "purpose": "DISPOSITION_EVALUATION_ONLY",
            "artifact": artifact,
            "policy": retained_policy,
            "requested_policy": request.policy.model_dump(mode="json") if request.policy else None,
            "evaluated_at": now.isoformat(),
            **evaluate_conditions(artifact, policy, request.requested_action, now, unavailable),
        }
        stored = c.execute(
            "INSERT INTO artifact_retention_evaluations(tenant_id,evaluation_id,"
            "exact_scope,actor_id,request_hash,proof_hash,payload) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING *",
            (
                p.scope.tenant_id,
                request.request_id,
                Jsonb(scope),
                p.actor_id,
                request_hash,
                _digest(proof),
                Jsonb(proof),
            ),
        ).fetchone()
        return _envelope(stored)


def history(p: Principal, evaluation_id: UUID) -> dict:
    require_permission(p, "ontology_read")
    scope = p.scope.model_dump(mode="json")
    with resource_connection(p) as conn, conn.cursor(row_factory=dict_row) as c:
        conn.execute("SELECT set_config('finai.exact_scope',%s,true)", (json.dumps(scope),))
        row = c.execute(
            "SELECT * FROM artifact_retention_evaluations "
            "WHERE tenant_id=%s AND evaluation_id=%s AND exact_scope=%s",
            (p.scope.tenant_id, evaluation_id, Jsonb(scope)),
        ).fetchone()
        if row is None:
            raise WorkspaceError(404, "Retention evaluation unavailable in exact context")
        return _envelope(row)


def artifact_history(p: Principal, request: RetentionHistoryRequest) -> dict:
    """Read retained proof by exact artifact; current bytes and policy are not dependencies."""
    require_permission(p, "ontology_read")
    scope = p.scope.model_dump(mode="json")
    query = (
        "SELECT * FROM artifact_retention_evaluations WHERE tenant_id=%s AND exact_scope=%s "
        "AND payload->'artifact'->'reference'=%s "
    )
    params: list[Any] = [
        p.scope.tenant_id,
        Jsonb(scope),
        Jsonb(request.artifact.model_dump(mode="json")),
    ]
    if request.before:
        query += "AND (recorded_at,evaluation_id)<(%s,%s) "
        params.extend([request.before.recorded_at, request.before.evaluation_id])
    query += "ORDER BY recorded_at DESC,evaluation_id DESC LIMIT %s"
    params.append(request.limit + 1)
    with resource_connection(p) as conn, conn.cursor(row_factory=dict_row) as c:
        conn.execute("SELECT set_config('finai.exact_scope',%s,true)", (json.dumps(scope),))
        rows = c.execute(query, params).fetchall()
    page = rows[: request.limit]
    next_cursor = None
    if len(rows) > request.limit:
        last = page[-1]
        next_cursor = {
            "recorded_at": last["recorded_at"].isoformat(),
            "evaluation_id": str(last["evaluation_id"]),
        }
    return {
        "items": [_envelope(row) for row in page],
        "next_cursor": next_cursor,
        "current_use_authorized": False,
    }
