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


def _migration_dependencies(root: Path) -> dict[str, str]:
    migration_root = root / "migrations"
    if (
        not migration_root.exists()
        and root.parent.name == "src"
        and (root.parent.parent / "pyproject.toml").is_file()
    ):
        migration_root = root.parent.parent / "migrations"
    migrations = sorted(migration_root.glob("*.sql"))
    if not migrations:
        raise WorkspaceError(503, "Packaged Function SQL dependency manifest is unavailable")
    return {
        "migrations/" + path.name: sha256(
            path.read_text(encoding="utf-8").encode("utf-8")
        ).hexdigest()
        for path in migrations
    }


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
    dependencies.update(_migration_dependencies(root))
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
            "typed_relationship_filters": True,
            "grouped_observation_counts": True,
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
                "query_predicates": 20,
                "traversal_steps": 4,
                "derived_properties": 8,
                "grouping_fields": 4,
                "grouping_coverage": "COMPLETE_BOUNDED_OBJECT_SET",
                "grouping_semantics": "EXACT_TYPED_STORED_VALUES",
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
                "typed_relationship_filters": False,
                "grouped_observation_counts": False,
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
    if spec.definition.group_count is not None:
        from finai_api.services.grouped_observations import validate_schema

        grouping = spec.definition.group_count
        schema = target(str(grouping.schema_id), str(item.resource_id), "FUNCTION_GROUP_SCHEMA")
        validate_schema(schema, grouping.fields)


def _pin(row: dict) -> dict:
    return {
        "resource_id": str(row["resource_id"]),
        "version_id": str(row["version_id"]),
        "content_hash": row["content_hash"],
    }


def plan(p: Principal, request: FunctionInvocation, *, defer_input: bool = False) -> dict:
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
    if not isinstance(spec.definition, WorksheetImplementation) and spec.definition.group_count:
        from finai_api.services.grouped_observations import validate_schema

        grouping = spec.definition.group_count
        schema = by_id.get(str(grouping.schema_id))
        if schema is None:
            raise WorkspaceError(409, "Grouping schema exact dependency is unavailable")
        validate_schema(schema, grouping.fields)
        if request.offset != 0:
            raise WorkspaceError(422, "Grouping requires a complete Object Set starting at zero")
        result["group_count"] = {"schema": _pin(schema), "fields": grouping.fields}
    if request.input_result is not None:
        if selected is None or source is not None:
            raise WorkspaceError(409, "Retained input requires the ontology Object Set adapter")
        if not defer_input:
            _retained_input(p, request, result)
    result["plan_hash"] = _digest(result)
    return result


def _retained_input(p: Principal, request: FunctionInvocation, compiled: dict) -> dict:
    """Resolve immutable shared evidence, never repeat the upstream Object Set query."""
    from finai_api.services.function_invocations import history

    assert request.input_result is not None
    retained = history(p, request.input_result.invocation_id)
    source = retained.get("output")
    if retained["status"] != "SUCCEEDED" or not isinstance(source, dict):
        raise WorkspaceError(409, "Retained input requires a successful Function receipt")
    selected = compiled["object_set"]
    if (
        source.get("implementation", {}).get("implementation_id") != IMPLEMENTATION_ID
        or source.get("definition_id") != selected["resource_id"]
        or source.get("definition_version_id") != selected["version_id"]
        or retained["receipt"]["exact_scope"] != p.scope.model_dump(mode="json")
        or datetime.fromisoformat(retained["receipt"]["request"]["valid_at"]) != request.valid_at
        or datetime.fromisoformat(retained["receipt"]["request"]["known_at"]) != request.known_at
        or source["query"]["limit"] > request.limit
    ):
        raise WorkspaceError(409, "Retained input Object Set, scope or time is incompatible")
    objects = source["objects"]
    if len(objects) > request.limit or len({obj["resource_id"] for obj in objects}) != len(objects):
        raise WorkspaceError(409, "Retained input page is invalid or exceeds the declared bound")
    with resource_connection(p) as conn, conn.cursor(row_factory=dict_row) as c:
        c.execute("SET LOCAL statement_timeout = '10s'")
        for obj in objects:
            row = c.execute(
                "SELECT to_jsonb(v)-'tenant_id' || "
                "jsonb_build_object('identity_key',i.identity_key) AS object "
                "FROM resource_versions v JOIN canonical_identities i USING(tenant_id,resource_id) "
                "WHERE v.tenant_id=%s AND v.resource_id=%s AND v.version_id=%s "
                "AND v.system_from<=%s",
                (
                    p.scope.tenant_id,
                    obj["resource_id"],
                    obj["version_id"],
                    datetime.fromisoformat(source["query"]["known_at"]),
                ),
            ).fetchone()
            if row is None or row["object"] != obj:
                raise WorkspaceError(409, "Retained input canonical version content is unavailable")
    return {
        **{
            key: source[key]
            for key in (
                "query",
                "total",
                "counts_by_type",
                "objects",
                "next_offset",
                "definition_id",
                "definition_version_id",
            )
        },
        **{
            key: source[key]
            for key in ("filter_schema_versions", "traversal_schema_versions")
            if key in source
        },
        "input_result": {
            "invocation_id": retained["invocation_id"],
            "receipt_hash": retained["receipt_hash"],
            "run_id": source["run_id"],
        },
    }


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
    result = (
        _retained_input(p, request, retained_plan)
        if request.input_result
        else ontology_definitions.run_set(
            p,
            UUID(selected["resource_id"]),
            UUID(selected["version_id"]),
            request.offset,
            request.limit,
            request.valid_at,
            request.known_at,
        )
    )
    query_known_at = datetime.fromisoformat(result["query"]["known_at"])
    grouped = {}
    if retained_plan.get("group_count"):
        from finai_api.services.grouped_observations import count_observations

        grouping = retained_plan["group_count"]
        with resource_connection(p) as conn, conn.cursor(row_factory=dict_row) as c:
            schema = c.execute(
                "SELECT v.*,i.identity_key FROM resource_versions v "
                "JOIN canonical_identities i USING(tenant_id,resource_id) "
                "WHERE v.tenant_id=%s AND v.resource_id=%s AND v.version_id=%s",
                (
                    p.scope.tenant_id,
                    grouping["schema"]["resource_id"],
                    grouping["schema"]["version_id"],
                ),
            ).fetchone()
        if schema is None or _pin(schema) != grouping["schema"]:
            raise WorkspaceError(409, "Grouping schema pin is unavailable")
        grouped = {"group_counts": count_observations(result, grouping, schema)}
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
        **grouped,
        "contract": "function-result/1",
        "function": retained_plan["function"],
        "implementation": retained_plan["implementation"],
        "plan_hash": retained_plan["plan_hash"],
        "derived_values": derived,
        "used_versions": used,
        "static_dependencies": retained_plan["static_dependencies"],
        "coverage": "RETAINED_INPUT_PAGE_ONLY" if request.input_result else "QUERY_PAGE_ONLY",
        "mode": "EVIDENCE_ANALYSIS_ONLY",
        "business_effect_authorized": False,
        "current_use_authorized": False,
    }
