"""Local API observations over canonical desired state; no deployment authority."""

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import Response
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from finai_api.domain.authority import canonical_sha256
from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services import fact_runs, function_execution
from finai_api.services.certification import _current
from finai_api.services.resources import resource_connection
from finai_api.services.upstream_authority import upstream_authority
from finai_api.services.workspace import WorkspaceError

_OBSERVER_INSTANCE_ID = str(uuid4())
_OBSERVER_STARTED_AT = datetime.now(UTC).isoformat()


class ObservationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: UUID = Field(default_factory=uuid4)
    desired_state: VersionReference


def _scope(conn: Any, p: Principal) -> dict:
    scope = p.scope.model_dump(mode="json")
    conn.execute("SELECT set_config('finai.exact_scope',%s,true)", (json.dumps(scope),))
    return scope


def _pin(row: dict) -> dict:
    return {
        "resource_id": str(row["resource_id"]),
        "version_id": str(row["version_id"]),
        "content_hash": row["content_hash"],
        "display_name": row["display_name"],
    }


def controls(cursor: Any, p: Principal, ref: VersionReference) -> tuple[dict, dict, dict]:
    desired = _current(cursor, p, ref)
    if desired["object_type"] != "DesiredState":
        raise WorkspaceError(409, "An exact reviewed DesiredState is required")

    def dependency(source: dict, field: str) -> dict:
        rows = cursor.execute(
            "SELECT DISTINCT target_resource_id,target_version_id "
            "FROM resource_dependencies WHERE tenant_id=%s AND version_id=%s AND relation=%s",
            (p.scope.tenant_id, source["version_id"], "FIELD:" + field),
        ).fetchall()
        if len(rows) != 1 or str(rows[0]["target_resource_id"]) != source["attributes"].get(field):
            raise WorkspaceError(409, "Runtime control exact dependency is unavailable")
        return _current(
            cursor,
            p,
            VersionReference(
                resource_id=rows[0]["target_resource_id"], version_id=rows[0]["target_version_id"]
            ),
        )

    agent = dependency(desired, "runtime_agent_id")
    target = dependency(desired, "deployment_target_id")
    agent_target = dependency(agent, "deployment_target_id")
    if any(
        row["access_entity"] not in (p.scope.legal_entity_id, "__PLATFORM__")
        for row in (desired, agent, target, agent_target)
    ):
        raise WorkspaceError(409, "Runtime controls must belong to this company scope")
    if (
        agent["object_type"] != "RuntimeAgent"
        or target["object_type"] != "DeploymentTarget"
        or agent_target["version_id"] != target["version_id"]
        or agent["attributes"]["definition"]["actor_id"] != p.actor_id
        or target["attributes"]["definition"]["environment_class"] != "LOCAL_DEVELOPMENT"
        or target["attributes"]["definition"]["component"] != "api"
    ):
        raise WorkspaceError(409, "This observer does not match the reviewed local API target")
    upstream_authority(cursor, p.scope.tenant_id, ref.version_id)
    return desired, agent, target


def collect(p: Principal) -> dict:
    from finai_api.api.routes import readiness

    loaded = {
        key: function_execution._STARTUP_MANIFEST[key]
        for key in ("code_sha256", "dependency_sha256")
    }
    disk = None
    try:
        manifest = function_execution._disk_manifest()
        disk = {key: manifest[key] for key in loaded}
    except Exception:
        pass
    health = readiness(Response())
    schema_version = 0
    try:
        with resource_connection(p) as conn:
            versions = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
            while schema_version + 1 in versions:
                schema_version += 1
    except Exception:
        health = {**health, "database": "unavailable"}
    return {
        "observed_at": datetime.now(UTC).isoformat(),
        "observer_instance_id": _OBSERVER_INSTANCE_ID,
        "observer_started_at": _OBSERVER_STARTED_AT,
        "loaded_identity": loaded,
        "disk_identity": disk,
        "disk_matches_loaded": disk == loaded,
        "health": health,
        "database_schema_version": schema_version,
        "identity_semantics": "FUNCTION_PACKAGE_STARTUP_SNAPSHOT_NOT_RELEASE_ATTESTATION",
    }


def classify(definition: dict, observation: dict) -> str:
    if observation["disk_identity"] is None or any(
        observation["health"].get(key) != "ready"
        for key in ("database", "schema", "evidence_store")
    ):
        return "DEGRADED"
    loaded = observation["loaded_identity"]
    if (
        not observation["disk_matches_loaded"]
        or loaded["code_sha256"] != definition["expected_code_sha256"]
        or loaded["dependency_sha256"] != definition["expected_dependency_sha256"]
        or observation["database_schema_version"] < definition["required_schema_version"]
    ):
        return "DRIFT"
    return "MATCH"


def _envelope(p: Principal, row: dict) -> dict:
    output = fact_runs.read_run(p, row["run_id"])
    original = ObservationRequest(
        request_id=row["request_id"],
        desired_state=VersionReference(
            resource_id=output["desired_state"]["resource_id"],
            version_id=output["desired_state"]["version_id"],
        ),
    )
    if (
        output.get("request_id") != str(row["request_id"])
        or canonical_sha256(original) != row["request_hash"]
        or row["proof_hash"] != row["run_id"].removeprefix("fcr_")
    ):
        raise WorkspaceError(409, "Runtime observation evidence mismatch")
    now = datetime.now(UTC)
    age = max(
        0.0, (now - datetime.fromisoformat(output["observation"]["observed_at"])).total_seconds()
    )
    stale = age > output["desired_definition"]["max_observation_age_seconds"]
    return {
        "request_id": str(row["request_id"]),
        "run_id": row["run_id"],
        "proof_hash": row["proof_hash"],
        "recorded_at": row["recorded_at"].isoformat(),
        "reported_state": output,
        "assessment": {
            "state": "STALE" if stale else output["recorded_state"],
            "checked_at": now.isoformat(),
            "age_seconds": age,
        },
        "current_use_authorized": False,
        "deployment_authorized": False,
    }


def capture(p: Principal, request: ObservationRequest) -> dict:
    require_permission(p, "ontology_admin")
    with resource_connection(p) as conn, conn.cursor(row_factory=dict_row) as cursor:
        scope = _scope(conn, p)
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (f"runtime-observation:{p.scope.tenant_id}:{request.request_id}",),
        )
        old = cursor.execute(
            "SELECT * FROM runtime_observations WHERE tenant_id=%s AND request_id=%s",
            (p.scope.tenant_id, request.request_id),
        ).fetchone()
        request_hash = canonical_sha256(request)
        if old:
            if old["request_hash"] != request_hash or old["actor_id"] != p.actor_id:
                raise WorkspaceError(409, "Observation request identity already used differently")
            return _envelope(p, old)
        desired, agent, target = controls(cursor, p, request.desired_state)
        observation = collect(p)
        output = fact_runs.retain_run(
            p,
            {
                "contract": "runtime-observation/1",
                "request_id": str(request.request_id),
                "desired_state": _pin(desired),
                "runtime_agent": _pin(agent),
                "deployment_target": _pin(target),
                "desired_definition": desired["attributes"]["definition"],
                "observation": observation,
                "recorded_state": classify(desired["attributes"]["definition"], observation),
                "release_provenance": "LOCAL_DEVELOPMENT_UNATTESTED",
                "deployment_authorized": False,
                "current_use_authorized": False,
            },
            runtime="local-api-observer/1",
        )
        row = cursor.execute(
            "INSERT INTO runtime_observations "
            "(tenant_id,request_id,exact_scope,actor_id,request_hash,run_id,proof_hash) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING *",
            (
                p.scope.tenant_id,
                request.request_id,
                Jsonb(scope),
                p.actor_id,
                request_hash,
                output["run_id"],
                output["run_id"].removeprefix("fcr_"),
            ),
        ).fetchone()
        if row is None:
            raise WorkspaceError(409, "Observation request identity already retained")
        return _envelope(p, row)


def history(p: Principal, request_id: UUID) -> dict:
    require_permission(p, "ontology_admin")
    with resource_connection(p) as conn, conn.cursor(row_factory=dict_row) as cursor:
        _scope(conn, p)
        row = cursor.execute(
            "SELECT * FROM runtime_observations WHERE tenant_id=%s AND request_id=%s",
            (p.scope.tenant_id, request_id),
        ).fetchone()
    if row is None:
        raise WorkspaceError(404, "Runtime observation unavailable in this exact scope")
    return _envelope(p, row)


def listing(
    p: Principal,
    limit: int = 20,
    before_recorded_at: datetime | None = None,
    before_request_id: UUID | None = None,
) -> dict:
    require_permission(p, "ontology_admin")
    if not 1 <= limit <= 50 or (before_recorded_at is None) != (before_request_id is None):
        raise WorkspaceError(422, "Invalid runtime observation page")
    params: list[Any] = [p.scope.tenant_id]
    seek = ""
    if before_recorded_at is not None:
        if before_recorded_at.tzinfo is None or before_recorded_at.utcoffset() is None:
            raise WorkspaceError(422, "Observation cursor requires timezone")
        seek = "AND (recorded_at,request_id)<(%s,%s) "
        params.extend([before_recorded_at, before_request_id])
    params.append(limit + 1)
    with resource_connection(p) as conn, conn.cursor(row_factory=dict_row) as cursor:
        _scope(conn, p)
        rows = cursor.execute(
            "SELECT * FROM runtime_observations WHERE tenant_id=%s "
            + seek
            + "ORDER BY recorded_at DESC,request_id DESC LIMIT %s",
            params,
        ).fetchall()
    page = rows[:limit]
    return {
        "items": [_envelope(p, row) for row in page],
        "has_more": len(rows) > limit,
        "next_cursor": {
            "recorded_at": page[-1]["recorded_at"].isoformat(),
            "request_id": str(page[-1]["request_id"]),
        }
        if len(rows) > limit
        else None,
    }
