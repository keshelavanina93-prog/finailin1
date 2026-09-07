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
        "maximum_materialized_rows": 1000,
        "maximum_materialized_pages": 10,
        "maximum_properties": 8,
        "capabilities": {
            "read": True,
            "query": True,
            "typed_relationship_filters": True,
            "versioned_interface_inputs": True,
            "versioned_type_group_inputs": True,
            "composed_derived_properties": True,
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
        result.pop("maximum_materialized_rows")
        result.pop("maximum_materialized_pages")
        result.update(
            implementation_id=implementation_id,
            maximum_rows=50,
            maximum_properties=0,
            maximum_columns=256,
            capabilities={
                **result["capabilities"],
                "query": False,
                "typed_relationship_filters": False,
                "versioned_interface_inputs": False,
                "versioned_type_group_inputs": False,
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


def validate_function(item: ResourceMutation, target: Callable[..., dict]) -> None:
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
    properties = []
    for identity in spec.definition.derived_property_ids:
        prop = target(str(identity), str(item.resource_id), "FUNCTION_DERIVED_PROPERTY")
        if prop["object_type"] != "DerivedProperty":
            raise WorkspaceError(409, "Function property input must be a canonical DerivedProperty")
        properties.append(prop)
    if spec.definition.retained_properties:
        from finai_api.services.derived_property_graph import resolve_with_loader

        cache = {}

        def load(identity, version):
            key = (str(identity), str(version))
            if key not in cache:
                cache[key] = target(
                    key[0], str(item.resource_id), "FUNCTION_RETAINED_PROPERTY:" + key[0], key[1]
                )
            return cache[key]

        graph = resolve_with_loader(
            [load(prop["resource_id"], prop["version_id"]) for prop in properties], load
        )
        _retained_property_contract(spec.definition.retained_properties, graph)
    if spec.definition.group_count is not None:
        from finai_api.services.grouped_observations import validate_schema

        grouping = spec.definition.group_count
        schema = target(str(grouping.schema_id), str(item.resource_id), "FUNCTION_GROUP_SCHEMA")
        validate_schema(schema, grouping.fields)

    if spec.definition.temporal_extent is not None:
        from finai_api.services.temporal_observations import validate_schema as temporal_schema

        extent = spec.definition.temporal_extent
        schema = target(str(extent.schema_id), str(item.resource_id), "FUNCTION_TEMPORAL_SCHEMA")
        temporal_schema(schema, extent.field)


def _pin(row: dict) -> dict:
    return {
        "resource_id": str(row["resource_id"]),
        "version_id": str(row["version_id"]),
        "content_hash": row["content_hash"],
    }


def _composed_graph(principal: Principal, properties: list[dict], *, force=False) -> dict | None:
    from finai_api.domain.ontology_definitions import DerivedDefinition
    from finai_api.services.derived_property_graph import references, resolve_with_loader

    rows = [
        ontology_definitions.definition(
            principal, UUID(prop["resource_id"]), UUID(prop["version_id"])
        )
        for prop in properties
    ]
    if not force and not any(
        list(
            references(DerivedDefinition.model_validate(row["attributes"]["definition"]).expression)
        )
        for row in rows
    ):
        return None
    return resolve_with_loader(
        rows,
        lambda identity, version: ontology_definitions.definition(principal, identity, version),
    )


def _retained_property_contract(references, graph):
    if not graph:
        raise WorkspaceError(409, "Retained calculated properties require an exact derived graph")
    nodes = {(node["resource_id"], node["version_id"]): node for node in graph["nodes"]}
    result = []
    for ref in references:
        node = nodes.get((str(ref.resource_id), str(ref.version_id)))
        if node is None:
            raise WorkspaceError(
                409, "Retained property is not an exact member of the derived graph"
            )
        result.append({**_pin(node), "schema": node["schema"]})
    return result


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
        # Evidence analysis distinguishes immutable provenance from active definitions.
        # Authoritative consumption keeps the guard's strict default and SQL checks.
        lineage_authority = upstream_authority(
            c,
            p.scope.tenant_id,
            request.function.version_id,
            allow_historical_provenance=True,
        )
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
    retained_properties = getattr(spec.definition, "retained_properties", [])
    if any(row.get("lineage_use") == "HISTORICAL" for row in lineage_authority):
        result["retained_provenance_authority"] = lineage_authority
    if retained_properties and request.input_result is None:
        raise WorkspaceError(
            422, "Configured retained properties require an upstream invocation input"
        )
    graph = _composed_graph(p, properties, force=bool(retained_properties))
    if graph is not None:
        from finai_api.services.derived_property_graph import public_graph

        result["derived_graph"] = public_graph(graph)
    if retained_properties:
        result["retained_properties"] = _retained_property_contract(retained_properties, graph)
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
    if not isinstance(spec.definition, WorksheetImplementation) and spec.definition.temporal_extent:
        from finai_api.services.temporal_observations import validate_schema as temporal_schema

        extent = spec.definition.temporal_extent
        schema = by_id.get(str(extent.schema_id))
        if schema is None:
            raise WorkspaceError(409, "Temporal schema exact dependency is unavailable")
        kind = temporal_schema(schema, extent.field)
        if request.offset != 0:
            raise WorkspaceError(
                422, "Temporal extent requires a complete Object Set starting at zero"
            )
        result["temporal_extent"] = {"schema": _pin(schema), "field": extent.field, "kind": kind}
    if not isinstance(spec.definition, WorksheetImplementation) and spec.definition.materialization:
        if request.offset != 0:
            raise WorkspaceError(422, "Materialization starts at offset zero")
        result["materialization"] = spec.definition.materialization.model_dump()
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
    materialization = compiled.get("materialization")
    if materialization:
        from finai_api.services.object_set_materialization import validate

        if source["query"]["limit"] != request.limit:
            raise WorkspaceError(409, "Retained materialization requires the same page size")
        with resource_connection(p) as conn:
            validate(source, materialization, selected, conn)
    elif source.get("materialization") is not None:
        raise WorkspaceError(409, "Retained materialization requires reviewed consumer bounds")
    if (not materialization and len(objects) > request.limit) or len(
        {obj["resource_id"] for obj in objects}
    ) != len(objects):
        raise WorkspaceError(409, "Retained input page is invalid or exceeds the declared bound")
    source_plan = None
    with resource_connection(p) as conn, conn.cursor(row_factory=dict_row) as c:
        c.execute("SET LOCAL statement_timeout = '10s'")
        if compiled.get("retained_properties"):
            c.execute(
                "SELECT set_config('finai.exact_scope',%s,true)",
                (json.dumps(p.scope.model_dump(mode="json")),),
            )
            intent = c.execute(
                "SELECT plan,plan_hash FROM function_invocations WHERE tenant_id=%s "
                "AND request_id=%s AND exact_scope=%s::jsonb",
                (
                    p.scope.tenant_id,
                    request.input_result.invocation_id,
                    json.dumps(p.scope.model_dump(mode="json")),
                ),
            ).fetchone()
            if (
                intent is None
                or intent["plan_hash"] != retained["receipt"]["plan_hash"]
                or source.get("plan_hash") != intent["plan_hash"]
                or _digest({k: v for k, v in intent["plan"].items() if k != "plan_hash"})
                != intent["plan_hash"]
            ):
                raise WorkspaceError(409, "Retained calculated input plan integrity is unavailable")
            source_plan = intent["plan"]
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
    source_result = {
        "invocation_id": retained["invocation_id"],
        "receipt_hash": retained["receipt_hash"],
        "run_id": source["run_id"],
    }
    calculated = {}
    if source_plan is not None:
        declared = [
            ontology_definitions.definition(p, UUID(ref["resource_id"]), UUID(ref["version_id"]))
            for ref in source_plan["derived_properties"]
        ]
        if [_pin(row) for row in declared] != source_plan["derived_properties"]:
            raise WorkspaceError(
                409, "Retained calculated output definitions differ from their plan"
            )
        calculated["consumed_property_values"] = _retained_property_values(
            compiled["retained_properties"],
            declared,
            objects,
            source.get("derived_values"),
            source_result,
        )
    return {
        **calculated,
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
            for key in (
                "filter_schema_versions",
                "traversal_schema_versions",
                "interface_bindings",
                "interface_values",
                "type_group_bindings",
                "type_group_values",
                "materialization",
            )
            if key in source
        },
        "input_result": source_result,
    }


def _retained_property_values(configured, declared, objects, values, source_result):
    """Validate upstream output rows; only selected exact properties seed evaluation."""
    from decimal import Decimal, DecimalException

    from finai_api.domain.ontology_definitions import DerivedDefinition

    props = {}
    for row in declared:
        if row["object_type"] != "DerivedProperty" or row["authority_state"] != "APPROVED":
            raise WorkspaceError(409, "Retained calculated output property is unavailable")
        model = DerivedDefinition.model_validate(row["attributes"]["definition"])
        schemas = [pin for pin in row["dependencies"] if pin["relation"] == "FIELD:schema_id"]
        if len(schemas) != 1:
            raise WorkspaceError(409, "Retained calculated output schema is unavailable")
        key = (str(row["resource_id"]), str(row["version_id"]))
        if key in props:
            raise WorkspaceError(409, "Retained calculated output has duplicate declared roots")
        props[key] = (row, model, schemas[0])
    selected = {(ref["resource_id"], ref["version_id"]): ref for ref in configured}
    for key, ref in selected.items():
        if (
            key not in props
            or _pin(props[key][0])
            != {k: ref[k] for k in ("resource_id", "version_id", "content_hash")}
            or _pin(props[key][2]) != ref["schema"]
        ):
            raise WorkspaceError(
                409, "Upstream Function did not declare the exact retained property output"
            )
    object_map = {(str(obj["resource_id"]), str(obj["version_id"])): obj for obj in objects}
    expected = {(rid, vid, oid, ovid) for rid, vid in props for oid, ovid in object_map}
    if not isinstance(values, list) or len(values) != len(expected):
        raise WorkspaceError(409, "Retained calculated outputs are missing or contain extra rows")
    seen = set()
    result = []
    for value in values:
        if not isinstance(value, dict):
            raise WorkspaceError(409, "Invalid retained calculated output row")
        if not {
            "definition_id",
            "definition_version_id",
            "object_id",
            "object_version_id",
            "name",
            "kind",
            "epistemic_state",
            "status",
            "value",
        }.issubset(value):
            raise WorkspaceError(409, "Retained calculated output row is incomplete")
        if "reason" in value and (
            not isinstance(value["reason"], str) or len(value["reason"]) > 2000
        ):
            raise WorkspaceError(409, "Retained calculated output reason is invalid")
        key = tuple(
            str(value.get(k))
            for k in ("definition_id", "definition_version_id", "object_id", "object_version_id")
        )
        if key not in expected or key in seen:
            raise WorkspaceError(
                409, "Retained calculated output has duplicate or mismatched exact pins"
            )
        seen.add(key)
        row, model, schema = props[key[:2]]
        obj = object_map[key[2:]]
        status, data = value.get("status"), value.get("value")
        if (
            value.get("kind") != model.result_kind
            or value.get("name") != model.name
            or value.get("epistemic_state") != "DERIVED"
        ):
            raise WorkspaceError(
                409, "Retained calculated output type differs from its exact property"
            )
        if status not in {"AVAILABLE", "MISSING_INPUT", "UNAVAILABLE", "NOT_APPLICABLE"}:
            raise WorkspaceError(409, "Retained calculated output status is invalid")
        if obj["object_type"] != schema["identity_key"]:
            if status != "NOT_APPLICABLE":
                raise WorkspaceError(409, "Retained calculated output applicability is invalid")
        elif status == "NOT_APPLICABLE":
            raise WorkspaceError(
                409, "Retained calculated output unexpectedly excludes its object type"
            )
        elif str(obj["schema_version_id"]) != str(schema["version_id"]) and status != "UNAVAILABLE":
            raise WorkspaceError(409, "Retained calculated output object schema is incompatible")
        if status == "AVAILABLE":
            if model.result_kind == "text":
                valid = isinstance(data, str)
            else:
                valid = isinstance(data, (str, int)) and not isinstance(data, bool)
                if valid:
                    try:
                        valid = len(str(data)) <= 4096
                        if valid:
                            ontology_definitions._bounded_decimal_text(Decimal(str(data)))
                    except (ValueError, DecimalException):
                        valid = False
            if not valid:
                raise WorkspaceError(
                    409, "Retained calculated output value violates its declared kind"
                )
        elif data is not None:
            raise WorkspaceError(409, "Unavailable retained calculated output cannot carry a value")
        if key[:2] in selected:
            result.append(
                {
                    **{
                        name: value[name]
                        for name in (
                            "object_id",
                            "object_version_id",
                            "definition_id",
                            "definition_version_id",
                            "name",
                            "kind",
                            "epistemic_state",
                            "status",
                            "value",
                        )
                    },
                    "content_hash": row["content_hash"],
                    "schema": _pin(schema),
                    "source_result": source_result,
                    **({"reason": value["reason"]} if isinstance(value.get("reason"), str) else {}),
                }
            )
    indexed = {
        (
            str(v["definition_id"]),
            str(v["definition_version_id"]),
            str(v["object_id"]),
            str(v["object_version_id"]),
        ): v
        for v in result
    }
    return [
        indexed[
            (ref["resource_id"], ref["version_id"], str(obj["resource_id"]), str(obj["version_id"]))
        ]
        for ref in configured
        for obj in objects
    ]


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
    if retained_plan.get("materialization") and request.input_result is None:
        from finai_api.services.object_set_materialization import collect

        result = collect(p, selected, request, retained_plan["materialization"])
    else:
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
        grouped = {
            "group_counts": count_observations(
                result, grouping, schema, materialized=bool(retained_plan.get("materialization"))
            )
        }
    if retained_plan.get("temporal_extent"):
        from finai_api.services.temporal_observations import extent_observations

        extent = retained_plan["temporal_extent"]
        with resource_connection(p) as conn, conn.cursor(row_factory=dict_row) as c:
            schema = c.execute(
                "SELECT v.*,i.identity_key FROM resource_versions v "
                "JOIN canonical_identities i USING(tenant_id,resource_id) "
                "WHERE v.tenant_id=%s AND v.resource_id=%s AND v.version_id=%s",
                (
                    p.scope.tenant_id,
                    extent["schema"]["resource_id"],
                    extent["schema"]["version_id"],
                ),
            ).fetchone()
        if schema is None or _pin(schema) != extent["schema"]:
            raise WorkspaceError(409, "Temporal schema pin is unavailable")
        grouped["temporal_extent"] = extent_observations(
            result, extent, schema, materialized=bool(retained_plan.get("materialization"))
        )
    properties = retained_plan["derived_properties"]
    graph = _composed_graph(p, properties, force=bool(retained_plan.get("retained_properties")))
    graph_output = {}
    if graph is not None:
        from finai_api.services.derived_property_graph import evaluate_graph, public_graph

        retained_graph = public_graph(graph)
        if retained_graph != retained_plan.get("derived_graph"):
            raise WorkspaceError(409, "Derived graph differs from the retained Function plan")
        derived = evaluate_graph(
            graph, result["objects"], retained_values=result.get("consumed_property_values")
        )
        graph_output["derived_graph"] = retained_graph
    else:
        if retained_plan.get("derived_graph") is not None:
            raise WorkspaceError(409, "Retained Function derived graph is unavailable")
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
        **graph_output,
        "used_versions": used,
        "static_dependencies": retained_plan["static_dependencies"],
        **(
            {"retained_provenance_authority": retained_plan["retained_provenance_authority"]}
            if "retained_provenance_authority" in retained_plan
            else {}
        ),
        "coverage": "COMPLETE_BOUNDED_MATERIALIZATION"
        if retained_plan.get("materialization")
        else "RETAINED_INPUT_PAGE_ONLY"
        if request.input_result
        else "QUERY_PAGE_ONLY",
        "mode": "EVIDENCE_ANALYSIS_ONLY",
        "business_effect_authorized": False,
        "current_use_authorized": False,
    }
