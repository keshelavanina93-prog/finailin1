"""Append-only, content-addressed calculation evidence under the invoking scope."""

import json
from collections.abc import Mapping, Sequence
from hashlib import sha256

from fastapi.encoders import jsonable_encoder
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services.resources import resource_connection
from finai_api.services.workspace import WorkspaceError
from finai_api.storage import connection, retained_source


def _source_lineage(payload: Mapping[str, object]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return the ordered retained-source pins carried by a calculation run.

    Only runs that explicitly carry both lists are source-replayable.  Older
    calculation runtimes remain readable; a partially populated lineage is a
    corrupt downstream reference and fails closed.
    """

    lineage = payload.get("lineage")
    if not isinstance(lineage, Mapping):
        return (), ()
    receipt_ids = lineage.get("receipt_ids", ())
    source_hashes = lineage.get("source_hashes", ())
    if receipt_ids in (None, ()) and source_hashes in (None, ()):
        return (), ()
    if not isinstance(receipt_ids, Sequence) or isinstance(receipt_ids, (str, bytes)):
        raise WorkspaceError(409, "Calculation source lineage is malformed")
    if not isinstance(source_hashes, Sequence) or isinstance(source_hashes, (str, bytes)):
        raise WorkspaceError(409, "Calculation source lineage is malformed")
    receipts = tuple(str(value) for value in receipt_ids)
    hashes = tuple(str(value) for value in source_hashes)
    if not receipts or len(receipts) != len(hashes) or len(set(receipts)) != len(receipts):
        raise WorkspaceError(409, "Calculation source lineage is incomplete")
    if any(
        len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
        for value in hashes
    ):
        raise WorkspaceError(409, "Calculation source lineage hash is malformed")
    return receipts, hashes


def _verify_source_lineage(principal: Principal, payload: Mapping[str, object]) -> None:
    """Re-read every retained input before exposing a downstream run.

    Content-addressed retention protects new reads, but a previously retained
    calculation must also be invalidated if its source object disappears or
    changes.  This check is deliberately limited to runs carrying the TB
    source lineage contract and never infers a replacement source.
    """

    receipt_ids, source_hashes = _source_lineage(payload)
    if not receipt_ids:
        return
    scope = principal.scope.model_dump(mode="json")
    with connection(principal.scope) as conn, conn.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            "SELECT receipt_id,exact_scope,source_bytes,source_storage,source_sha256 "
            "FROM hydration_runs WHERE tenant_id=%s AND exact_scope=%s "
            "AND receipt_id=ANY(%s::text[])",
            (principal.scope.tenant_id, Jsonb(scope), list(receipt_ids)),
        ).fetchall()
    by_id = {str(row["receipt_id"]): row for row in rows}
    if set(by_id) != set(receipt_ids):
        raise WorkspaceError(409, "Calculation source evidence is unavailable; run invalidated")
    for receipt_id, expected_hash in zip(receipt_ids, source_hashes, strict=True):
        row = by_id[receipt_id]
        if str(row["source_sha256"]) != expected_hash:
            raise WorkspaceError(409, "Calculation source hash changed; run invalidated")
        try:
            content = retained_source(principal.scope, row)
        except Exception as exc:
            raise WorkspaceError(
                409, "Calculation source evidence failed integrity verification"
            ) from exc
        if sha256(content).hexdigest() != expected_hash:
            raise WorkspaceError(409, "Calculation source bytes changed; run invalidated")


def retain_run(
    principal: Principal, result: dict, *, runtime: str = "accounting-contracts/2"
) -> dict:
    require_permission(principal, "ontology_read")
    scope = principal.scope.model_dump(mode="json")
    read_permissions = set(principal.permissions)
    read_contract = {}
    if runtime == "shared-functions/1":
        read_permissions.intersection_update(
            {"read", "ontology_read", "ontology_admin", "restricted_read"}
        )
        read_contract = {"read_permission_contract": "SHARED_FUNCTION_READ_CAPABILITIES_V1"}
    payload = jsonable_encoder(
        {
            **result,
            "scope": scope,
            "calculation_runtime": runtime,
            "read_permissions": sorted(read_permissions),
            **read_contract,
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
    _verify_source_lineage(principal, payload)
    versions = set()

    def collect(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if (
                    key
                    in {
                        "version_id",
                        "contract_version_id",
                        "object_version_id",
                        "definition_version_id",
                        "schema_version_id",
                    }
                    and child is not None
                ):
                    versions.add(str(child))
                else:
                    collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(payload)
    with resource_connection(principal) as conn:
        retained = conn.execute(
            "SELECT count(DISTINCT version_id) FROM resource_versions "
            "WHERE tenant_id=%s AND version_id=ANY(%s::uuid[])",
            (principal.scope.tenant_id, sorted(versions)),
        ).fetchone()
    if retained is None:
        raise WorkspaceError(404, "Calculation inputs are unavailable in current access context")
    count = retained[0]
    if count != len(versions):
        raise WorkspaceError(404, "Calculation inputs are unavailable in current access context")
    return payload
