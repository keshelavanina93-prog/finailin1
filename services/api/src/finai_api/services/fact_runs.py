"""Append-only, content-addressed calculation evidence under the invoking scope."""

import json
from hashlib import sha256

from fastapi.encoders import jsonable_encoder
from psycopg.types.json import Jsonb

from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services.resources import resource_connection
from finai_api.services.workspace import WorkspaceError
from finai_api.storage import connection


def retain_run(principal: Principal, result: dict) -> dict:
    require_permission(principal, "ontology_read")
    scope = principal.scope.model_dump(mode="json")
    payload = jsonable_encoder(
        {
            **result,
            "scope": scope,
            "calculation_runtime": "accounting-contracts/2",
            "read_permissions": sorted(principal.permissions),
        }
    )
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    if len(encoded) > 16_000_000:
        raise WorkspaceError(422, "Calculation evidence exceeds 16 MB; narrow the fact scope")
    run_id = "fcr_" + sha256(encoded).hexdigest()
    payload["run_id"] = run_id
    with connection(principal.scope) as conn:
        conn.execute("SELECT set_config('finai.exact_scope',%s,true)", (json.dumps(scope),))
        conn.execute(
            "INSERT INTO fact_calculation_runs(tenant_id,run_id,exact_scope,payload,actor_id) "
            "VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (principal.scope.tenant_id, run_id, Jsonb(scope), Jsonb(payload), principal.actor_id),
        )
    return payload


def read_run(principal: Principal, run_id: str) -> dict:
    require_permission(principal, "ontology_read")
    scope = principal.scope.model_dump(mode="json")
    with connection(principal.scope) as conn:
        conn.execute("SELECT set_config('finai.exact_scope',%s,true)", (json.dumps(scope),))
        row = conn.execute(
            "SELECT payload FROM fact_calculation_runs WHERE tenant_id=%s AND run_id=%s "
            "AND exact_scope=%s",
            (principal.scope.tenant_id, run_id, Jsonb(scope)),
        ).fetchone()
    if not row or not set(row[0]["read_permissions"]).issubset(principal.permissions):
        raise WorkspaceError(404, "Calculation run unavailable in current access context")
    payload = row[0]
    expected = (
        "fcr_"
        + sha256(
            json.dumps(
                {key: value for key, value in payload.items() if key != "run_id"},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
    )
    if expected != run_id:
        raise WorkspaceError(409, "Calculation run integrity verification failed")
    versions = set()

    def collect(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"version_id", "contract_version_id"}:
                    versions.add(str(child))
                else:
                    collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(payload)
    with resource_connection(principal) as conn:
        count = conn.execute(
            "SELECT count(DISTINCT version_id) FROM resource_versions "
            "WHERE tenant_id=%s AND version_id=ANY(%s::uuid[])",
            (principal.scope.tenant_id, sorted(versions)),
        ).fetchone()[0]
    if count != len(versions):
        raise WorkspaceError(404, "Calculation inputs are unavailable in current access context")
    return payload
