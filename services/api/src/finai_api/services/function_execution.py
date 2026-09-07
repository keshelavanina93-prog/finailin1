"""First shared Function adapter: pinned read-only ontology analysis, no business effects."""

import importlib.metadata
import json
import platform
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row

from finai_api.domain.function_execution import (
    FunctionDefinition,
    FunctionInvocation,
    WorksheetImplementation,
)
from finai_api.domain.resources import ResourceMutation
from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services import ontology_definitions
from finai_api.services.certification import _current
from finai_api.services.resources import resource_connection
from finai_api.services.upstream_authority import upstream_authority
from finai_api.services.workspace import WorkspaceError

IMPLEMENTATION_ID = "ontology.object-set-derived/v1"
WORKSHEET_IMPLEMENTATION_ID = "source.retained-xls-worksheet/v1"


def _digest(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _disk_manifest() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]

    def source_hash(path: Path) -> str:
        return sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()

    code = {
        name: source_hash(root / name)
        for name in ("services/function_execution.py", "domain/function_execution.py")
    }
    # Bind the installed application package rather than guessing a partial transitive
    # import list. Paths are package-relative and universal newlines remove CRLF drift.
    dependencies = {
        path.relative_to(root).as_posix(): source_hash(path) for path in sorted(root.rglob("*.py"))
    }
    migration_root = root.parents[1] / "migrations"
    migrations = sorted(migration_root.glob("*.sql"))
    if not migrations:
        raise WorkspaceError(503, "Packaged Function SQL dependency manifest is unavailable")
    dependencies.update({"migrations/" + path.name: source_hash(path) for path in migrations})
    dependencies["python"] = platform.python_version()
    for package in (
        "pydantic",
        "pydantic-core",
        "psycopg",
        "psycopg-binary",
        "fastapi",
        "pydantic-settings",
        "xlrd",
    ):
        dependencies[package] = importlib.metadata.version(package)
    return {
        "implementation_id": IMPLEMENTATION_ID,
        "determinism": "DETERMINISTIC_FOR_PINNED_INPUTS",
        "code_sha256": _digest(code),
        "dependency_sha256": _digest(dependencies),
        "mode": "EVIDENCE_ANALYSIS_ONLY",
        "maximum_rows": 200,
        "maximum_properties": 8,
        "capabilities": {
            "read": True,
            "query": True,
            "snapshot": True,
            "snapshot_semantics": "CANONICAL_VALID_AND_KNOWN_TIME_QUERY",
            "incremental": False,
            "cdc": False,
            "stream": False,
            "write": False,
            "update": False,
            "delete": False,
            "transaction": "NO_SOURCE_WRITE_TRANSACTION",
            "atomicity": "NO_SOURCE_WRITE; SHARED_IMMUTABLE_TERMINAL_RECEIPT",
            "idempotency": "SHARED_INVOCATION_REQUEST_ID_AND_PINNED_PLAN_REPLAY",
            "source_write_exactly_once": False,
            "simulation": False,
            "acknowledgement": "RETAINED_COMPUTATION_RECEIPT_ONLY",
            "readback": "SHARED_IMMUTABLE_FUNCTION_RESULT",
            "reversal": False,
            "formula_execution": False,
            "limits": {
                "returned_rows": 200,
                "derived_properties": 8,
                "coverage": "QUERY_PAGE_ONLY",
                "database_scan_limit": None,
            },
        },
    }


# Capture once while this executable module is loaded. Returning a freshly hashed
# deployment after an edit would misidentify the code already loaded in this process.
_STARTUP_MANIFEST = _disk_manifest()


def manifest(implementation_id: str = IMPLEMENTATION_ID) -> dict[str, Any]:
    try:
        current = _disk_manifest()
    except (OSError, importlib.metadata.PackageNotFoundError) as exc:
        raise WorkspaceError(
            503, "Function package changed; restart the runtime before execution"
        ) from exc
    if current != _STARTUP_MANIFEST:
        raise WorkspaceError(503, "Function package changed; restart the runtime before execution")
    if implementation_id not in (IMPLEMENTATION_ID, WORKSHEET_IMPLEMENTATION_ID):
        raise WorkspaceError(422, "Function implementation is not installed")
    result = deepcopy(_STARTUP_MANIFEST)
    if implementation_id == WORKSHEET_IMPLEMENTATION_ID:
        result.update(
            implementation_id=implementation_id,
            maximum_rows=50,
            maximum_properties=0,
            maximum_columns=256,
            capabilities={
                **result["capabilities"],
                "query": False,
                "snapshot_semantics": "IMMUTABLE_RETAINED_BYTES_WITH_EXACT_HASH_AND_SCOPE",
                "readback": "HASH_VERIFIED_SOURCE_BYTES_AND_SHARED_IMMUTABLE_FUNCTION_RESULT",
                "limits": {
                    "returned_rows": 50,
                    "columns": 256,
                    "source_bytes": 32000000,
                    "derived_properties": 0,
                    "coverage": "REVIEWED_WORKSHEET_PAGE_ONLY",
                    "database_scan_limit": None,
                },
            },
        )
    return result


def _check_implementation(spec: FunctionDefinition) -> dict:
    current = manifest(spec.definition.implementation_id)
    expected = spec.definition.model_dump(mode="json")
    if any(
        expected[key] != current[key]
        for key in ("implementation_id", "determinism", "code_sha256", "dependency_sha256")
    ):
        raise WorkspaceError(
            409, "Function implementation differs from the installed executable manifest"
        )
    return current


def validate_function(item: ResourceMutation, target: Callable[[str, str, str], dict]) -> None:
    spec = FunctionDefinition.model_validate(item.attributes)
    _check_implementation(spec)
    if isinstance(spec.definition, WorksheetImplementation):
        selected = target(str(spec.evidence_id), str(item.resource_id), "FIELD:evidence_id")
        if (
            selected["object_type"] != "SourceEvidence"
            or selected["attributes"].get("sha256") != spec.definition.source_sha256
        ):
            raise WorkspaceError(
                409, "Worksheet Function requires matching canonical SourceEvidence"
            )
        return
    selected = target(str(spec.object_set_id), str(item.resource_id), "FIELD:object_set_id")
    if selected["object_type"] != "ObjectSetDefinition":
        raise WorkspaceError(409, "Function requires a canonical Object Set definition")
    for identity in spec.definition.derived_property_ids:
        prop = target(str(identity), str(item.resource_id), "FUNCTION_DERIVED_PROPERTY")
        if prop["object_type"] != "DerivedProperty":
            raise WorkspaceError(409, "Function property input must be a canonical DerivedProperty")


def _pin(row: dict) -> dict:
    return {
        "resource_id": str(row["resource_id"]),
        "version_id": str(row["version_id"]),
        "content_hash": row["content_hash"],
    }


def plan(p: Principal, request: FunctionInvocation) -> dict:
    require_permission(p, "ontology_read")
    if request.known_at > datetime.now(UTC):
        raise WorkspaceError(422, "Function knowledge time cannot be in the future")
    with resource_connection(p) as conn, conn.cursor(row_factory=dict_row) as c:
        function = _current(c, p, request.function)
        if (
            function["object_type"] != "FunctionDefinition"
            or function["access_entity"] != p.scope.legal_entity_id
        ):
            raise WorkspaceError(409, "Function must belong to the selected company context")
        spec = FunctionDefinition.model_validate(function["attributes"])
        implementation = _check_implementation(spec)
        pins = c.execute(
            "SELECT DISTINCT v.* FROM resource_dependencies d JOIN resource_versions v "
            "ON v.tenant_id=d.tenant_id AND v.resource_id=d.target_resource_id "
            "AND v.version_id=d.target_version_id WHERE d.tenant_id=%s AND d.version_id=%s",
            (p.scope.tenant_id, request.function.version_id),
        ).fetchall()
        by_id = {str(row["resource_id"]): row for row in pins}
        selected = by_id.get(str(spec.object_set_id))
        source = None
        if isinstance(spec.definition, WorksheetImplementation):
            from finai_api.services.worksheet_function import source_plan

            source = source_plan(p, request, spec, by_id)
        elif selected is None or selected["object_type"] != "ObjectSetDefinition":
            raise WorkspaceError(409, "Function Object Set exact dependency is unavailable")
        properties = []
        for identity in spec.definition.derived_property_ids:
            prop = by_id.get(str(identity))
            if prop is None or prop["object_type"] != "DerivedProperty":
                raise WorkspaceError(
                    409, "Function derived-property exact dependency is unavailable"
                )
            properties.append(_pin(prop))
        # Existing lineage guard checks each current exact dependency and any material withdrawal.
        upstream_authority(c, p.scope.tenant_id, request.function.version_id)
    result = {
        "contract": "function-plan/1",
        "request": request.model_dump(mode="json"),
        "exact_scope": p.scope.model_dump(mode="json"),
        "mode": "EVIDENCE_ANALYSIS_ONLY",
        "function": _pin(function),
        "implementation": implementation,
        "object_set": _pin(selected) if selected else None,
        "derived_properties": properties,
        "static_dependencies": sorted(
            [_pin(row) for row in pins], key=lambda row: row["version_id"]
        ),
    }
    if source is not None:
        result["source_document"] = source
    result["plan_hash"] = _digest(result)
    return result


def execute_plan(p: Principal, retained_plan: dict) -> dict:
    """Internal invocation runner; callers submit typed requests, never execution plans."""
    if _digest(
        {key: value for key, value in retained_plan.items() if key != "plan_hash"}
    ) != retained_plan.get("plan_hash"):
        raise WorkspaceError(409, "Function execution plan failed integrity verification")
    request = FunctionInvocation.model_validate(retained_plan["request"])
    if plan(p, request) != retained_plan:
        raise WorkspaceError(
            409, "Function plan no longer matches installed implementation and exact context"
        )
    if retained_plan["implementation"]["implementation_id"] == WORKSHEET_IMPLEMENTATION_ID:
        from finai_api.services.worksheet_function import execute

        return execute(p, request, retained_plan)
    selected = retained_plan["object_set"]
    result = ontology_definitions.run_set(
        p,
        UUID(selected["resource_id"]),
        UUID(selected["version_id"]),
        request.offset,
        request.limit,
        request.valid_at,
        request.known_at,
    )
    query_known_at = datetime.fromisoformat(result["query"]["known_at"])
    properties = retained_plan["derived_properties"]
    derived = ontology_definitions.derived_values(
        p,
        result["objects"],
        [UUID(prop["resource_id"]) for prop in properties],
        {UUID(prop["resource_id"]): UUID(prop["version_id"]) for prop in properties},
    )
    used = []
    with resource_connection(p) as conn, conn.cursor(row_factory=dict_row) as c:
        for obj in result["objects"]:
            state = c.execute(
                "SELECT payload FROM resource_lifecycle_events WHERE tenant_id=%s "
                "AND version_id=%s AND recorded_at<=%s "
                "ORDER BY recorded_at DESC,event_id DESC LIMIT 1",
                (p.scope.tenant_id, obj["version_id"], query_known_at),
            ).fetchone()
            used.append(
                {
                    **_pin(obj),
                    "material_state": state["payload"] if state else "UNESTABLISHED",
                    "known_at": query_known_at.isoformat(),
                }
            )
    return {
        **result,
        "contract": "function-result/1",
        "function": retained_plan["function"],
        "implementation": retained_plan["implementation"],
        "plan_hash": retained_plan["plan_hash"],
        "derived_values": derived,
        "used_versions": used,
        "static_dependencies": retained_plan["static_dependencies"],
        "coverage": "QUERY_PAGE_ONLY",
        "mode": "EVIDENCE_ANALYSIS_ONLY",
        "business_effect_authorized": False,
        "current_use_authorized": False,
    }
