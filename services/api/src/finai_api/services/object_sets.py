"""Set operations over canonical identities and immutable dependency pins."""

from datetime import UTC, datetime
from typing import Any

from psycopg.errors import QueryCanceled
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from finai_api.domain.object_sets import (
    FilterSchemaVersion,
    ObjectSetQuery,
    ObjectSetResult,
    TraversalSchemaVersion,
)
from finai_api.domain.review import Principal
from finai_api.services.object_filter_contract import RANGE_PATTERNS, validate_filters
from finai_api.services.resources import resource_connection
from finai_api.services.workspace import WorkspaceError


def _schema_compat_sql(alias, schema_cte, field, args):
    args.append(field)
    return (
        f"EXISTS (SELECT 1 FROM {schema_cte} fs JOIN versions os "
        f"ON os.version_id={alias}.schema_version_id AND os.object_type='SchemaDefinition' "
        "AND os.authority_state='APPROVED' CROSS JOIN LATERAL "
        "(SELECT %s::text AS field) f "
        f"WHERE fs.identity_key={alias}.object_type AND fs.authority_state='APPROVED' "
        "AND os.attributes->'fields'->f.field=fs.attributes->'fields'->f.field)"
    )


def _filter_sql(filters, alias, schema_cte, args, exact_schema=False):
    predicate = ""
    for condition in filters:
        if exact_schema:
            predicate += " AND " + _schema_compat_sql(alias, schema_cte, condition.field, args)
        if condition.operator == "eq":
            predicate += " AND attributes @> %s::jsonb"
            args.append(Jsonb({condition.field: condition.value}))
        else:
            operator = {"lt": "<", "lte": "<=", "gt": ">", "gte": ">="}[condition.operator]
            predicate += f" AND EXISTS (SELECT 1 FROM {schema_cte} fs "
            predicate += f"JOIN versions os ON os.version_id={alias}.schema_version_id "
            predicate += "AND os.object_type='SchemaDefinition' AND os.authority_state='APPROVED' "
            predicate += "CROSS JOIN LATERAL (SELECT %s::text AS field,%s::text AS threshold) f "
            predicate += f"WHERE fs.identity_key={alias}.object_type "
            predicate += "AND fs.authority_state='APPROVED' "
            predicate += "AND os.attributes->'fields'->f.field->>'kind'="
            predicate += "fs.attributes->'fields'->f.field->>'kind' "
            args += [condition.field, str(condition.value) if condition.value is not None else None]
            predicate += "AND CASE os.attributes->'fields'->f.field->>'kind' "
            for kind, sql_type, json_type in (
                ("integer", "numeric", "number"),
                ("decimal", "numeric", "string"),
                ("date", "date", "string"),
                ("datetime", "timestamptz", "string"),
            ):
                value = f"{alias}.attributes->>f.field"
                predicate += f"WHEN '{kind}' THEN CASE WHEN "
                predicate += f"jsonb_typeof({alias}.attributes->f.field)='{json_type}' "
                if kind in RANGE_PATTERNS:
                    predicate += f"AND {value} ~ %s AND f.threshold ~ %s "
                    args += ["^" + RANGE_PATTERNS[kind] + "$", "^" + RANGE_PATTERNS[kind] + "$"]
                predicate += f"AND pg_input_is_valid({value},'{sql_type}') "
                predicate += f"AND pg_input_is_valid(f.threshold,'{sql_type}') "
                predicate += f"THEN ({value})::{sql_type} {operator} "
                predicate += f"(CASE WHEN pg_input_is_valid(f.threshold,'{sql_type}') "
                predicate += f"THEN f.threshold ELSE NULL END)::{sql_type} "
                predicate += "ELSE false END "
            predicate += "ELSE false END)"
    return predicate


def _stage_contracts(conn, principal, request, root_types):
    """Resolve typed destinations even when the requested root has no instances."""
    if not any(step.filters for step in request.traversal):
        return {}
    with conn.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            "SELECT * FROM (SELECT DISTINCT ON(v.resource_id) v.*,i.identity_key "
            "FROM resource_versions v JOIN canonical_identities i USING(tenant_id,resource_id) "
            "WHERE v.tenant_id=%s AND v.object_type IN ('SchemaDefinition','LinkType') "
            "AND v.system_from<=%s "
            "AND v.valid_from<=%s AND (v.valid_to IS NULL OR v.valid_to>%s) "
            "ORDER BY v.resource_id,v.system_from DESC,v.version_id) selected "
            "WHERE authority_state='APPROVED' LIMIT 2001",
            (principal.scope.tenant_id, request.known_at, request.valid_at, request.valid_at),
        ).fetchall()
    if len(rows) > 2000:
        raise WorkspaceError(409, "Traversal type discovery exceeds its bounded schema inventory")
    schemas = {r["identity_key"]: r for r in rows if r["object_type"] == "SchemaDefinition"}
    links = {r["identity_key"]: r for r in rows if r["object_type"] == "LinkType"}
    current = set(root_types)
    result = {}
    for index, step in enumerate(request.traversal, 1):
        if not current.issubset(schemas):
            raise WorkspaceError(422, "Traversal schema is unavailable at the requested time")
        if step.kind == "link":
            link = links.get(step.name)
            if link is None:
                raise WorkspaceError(422, "Traversal link type is unavailable")
            inputs = set(
                link["attributes"]["sources" if step.direction == "outgoing" else "targets"]
            )
            outputs = set(
                link["attributes"]["targets" if step.direction == "outgoing" else "sources"]
            )
            if "*" in outputs or ("*" not in inputs and not current.intersection(inputs)):
                raise WorkspaceError(422, "Traversal requires compatible explicit link endpoints")
        elif step.direction == "outgoing":
            outputs = set()
            for name in current:
                spec = schemas[name]["attributes"]["fields"].get(step.name, {})
                if spec.get("kind") != "reference" or spec.get("target_type") in (None, "*"):
                    raise WorkspaceError(422, "Traversal requires a declared typed reference")
                outputs.add(spec["target_type"])
        else:
            outputs = {
                name
                for name, schema in schemas.items()
                if schema["attributes"]["fields"].get(step.name, {}).get("kind") == "reference"
                and schema["attributes"]["fields"][step.name].get("target_type") in current
            }
        if not outputs or not outputs.issubset(schemas):
            raise WorkspaceError(422, "Traversal destination schema is unavailable")
        current = outputs
        if step.filters:
            selected = [schemas[name] for name in sorted(current)]
            for schema in selected:
                validate_filters(step.filters, schema["attributes"]["fields"])
            for condition in step.filters:
                if len({s["attributes"]["fields"][condition.field]["kind"] for s in selected}) != 1:
                    raise WorkspaceError(
                        422, "Traversal filters require compatible destination field kinds"
                    )
                if condition.operator != "eq":
                    kind = selected[0]["attributes"]["fields"][condition.field]["kind"]
                    sql_type = {
                        "integer": "numeric",
                        "decimal": "numeric",
                        "date": "date",
                        "datetime": "timestamptz",
                    }[kind]
                    if (
                        conn.execute(
                            "SELECT pg_input_is_valid(%s,%s)", (str(condition.value), sql_type)
                        ).fetchone()[0]
                        is not True
                    ):
                        raise WorkspaceError(
                            422, "Traversal threshold exceeds supported exact representation"
                        )
            result[index] = selected
    return result


def query_objects(
    principal: Principal, request: ObjectSetQuery, types: list[str] | None = None
) -> ObjectSetResult:
    with resource_connection(principal) as conn:
        conn.execute("SELECT set_config('statement_timeout','10000',true)")
        if any(step.filters for step in request.traversal):
            conn.execute(
                "SELECT pg_advisory_xact_lock_shared(hashtextextended(%s,0))",
                (f"canonical:{principal.scope.tenant_id}",),
            )
        try:
            return _query_objects(principal, request, types, conn)
        except QueryCanceled as exc:
            raise WorkspaceError(
                409, "Object traversal exceeded its execution budget; no partial results returned"
            ) from exc


def _query_objects(
    principal: Principal, request: ObjectSetQuery, types: list[str] | None, conn: Any
) -> ObjectSetResult:
    now = datetime.now(UTC)
    request = request.model_copy(
        update={
            "valid_at": request.valid_at or now,
            "known_at": request.known_at or now,
        }
    )
    # One statement gives counts, page and traversal a single database snapshot.
    # Only internal CTE names are interpolated; every caller value is a parameter.
    root_types = types if types is not None else [request.object_type]
    stage_schemas = _stage_contracts(conn, principal, request, root_types)
    args: list[Any] = [principal.scope.tenant_id, request.known_at]
    ctes = [
        "versions AS NOT MATERIALIZED (SELECT v.*,i.identity_key FROM resource_versions v "
        "JOIN canonical_identities i USING(tenant_id,resource_id) "
        "WHERE v.tenant_id=%s AND v.system_from<=%s)",
    ]
    if request.filters:
        ctes.append(
            "filter_schema_candidates AS (SELECT DISTINCT ON(resource_id) * FROM versions "
            "WHERE object_type='SchemaDefinition' AND identity_key=ANY(%s::text[]) "
            "AND valid_from<=%s AND (valid_to IS NULL OR valid_to>%s) "
            "ORDER BY resource_id,system_from DESC,version_id)"
        )
        args += [root_types, request.valid_at, request.valid_at]
    # Every traversal starts with a typed root. Incoming/link destinations are resolved
    # by exact dependencies below, never by materializing unrelated tenant history.
    ctes.append(
        "root_versions AS (SELECT v.*,i.identity_key FROM resource_versions v "
        "JOIN canonical_identities i USING(tenant_id,resource_id) "
        "WHERE v.tenant_id=%s AND v.system_from<=%s "
        "AND v.object_type=ANY(%s::text[]) AND i.object_type=ANY(%s::text[]))"
    )
    args += [principal.scope.tenant_id, request.known_at, root_types, root_types]
    ctes += [
        "effective AS (SELECT DISTINCT ON(resource_id) * FROM root_versions "
        "WHERE valid_from<=%s AND (valid_to IS NULL OR valid_to>%s) "
        "ORDER BY resource_id,system_from DESC,version_id)",
        "current_objects AS (SELECT * FROM effective WHERE authority_state='APPROVED')",
    ]
    args += [request.valid_at, request.valid_at, root_types]
    predicate = "object_type=ANY(%s::text[])"
    if request.resource_ids is not None:
        predicate += " AND resource_id=ANY(%s::uuid[])"
        args.append(request.resource_ids)
    predicate += _filter_sql(request.filters, "current_objects", "filter_schema_candidates", args)
    predicate += " AND position(lower(%s) in lower(display_name || ' ' || identity_key))>0"
    args.append(request.search)
    ctes.append("s0 AS (SELECT * FROM current_objects WHERE " + predicate + ")")
    invalid_stage_ctes = []
    for index, step in enumerate(request.traversal, 1):
        previous = f"s{index - 1}"
        if step.kind == "reference":
            if step.direction == "outgoing":
                destination = (
                    "JOIN LATERAL (SELECT * FROM versions pinned "
                    "WHERE pinned.tenant_id=d.tenant_id "
                    "AND pinned.resource_id=d.target_resource_id "
                    "AND pinned.version_id=d.target_version_id LIMIT 1) t ON true "
                )
                sql = (
                    f"SELECT DISTINCT t.* FROM {previous} s "
                    "JOIN resource_dependencies d ON d.tenant_id=s.tenant_id "
                    "AND d.version_id=s.version_id AND d.relation=%s "
                    + destination
                    + "WHERE t.authority_state='APPROVED'"
                )
            else:
                sql = (
                    f"SELECT DISTINCT t.* FROM {previous} s "
                    "JOIN resource_dependencies d ON d.tenant_id=s.tenant_id "
                    "AND d.target_resource_id=s.resource_id "
                    "AND d.target_version_id=s.version_id AND d.relation=%s "
                    "JOIN versions candidate ON candidate.tenant_id=d.tenant_id "
                    "AND candidate.version_id=d.version_id "
                    "JOIN LATERAL (SELECT * FROM versions selected "
                    "WHERE selected.tenant_id=candidate.tenant_id "
                    "AND selected.resource_id=candidate.resource_id "
                    "AND selected.valid_from<=%s "
                    "AND (selected.valid_to IS NULL OR selected.valid_to>%s) "
                    "ORDER BY selected.system_from DESC,selected.version_id LIMIT 1) t "
                    "ON t.version_id=d.version_id WHERE t.authority_state='APPROVED'"
                )
            args.append("FIELD:" + step.name)
            if step.direction == "incoming":
                args += [request.valid_at, request.valid_at]
        else:
            source = "source_id" if step.direction == "outgoing" else "target_id"
            target = "target_id" if step.direction == "outgoing" else "source_id"
            sql = (
                f"SELECT DISTINCT t.* FROM {previous} s "
                "JOIN resource_dependencies a ON a.tenant_id=s.tenant_id "
                "AND a.target_resource_id=s.resource_id "
                f"AND a.target_version_id=s.version_id AND a.relation='FIELD:{source}' "
                "JOIN versions candidate ON candidate.tenant_id=a.tenant_id "
                "AND candidate.version_id=a.version_id AND candidate.object_type='Relationship' "
                "JOIN LATERAL (SELECT * FROM versions selected "
                "WHERE selected.tenant_id=candidate.tenant_id "
                "AND selected.resource_id=candidate.resource_id AND selected.valid_from<=%s "
                "AND (selected.valid_to IS NULL OR selected.valid_to>%s) "
                "ORDER BY selected.system_from DESC,selected.version_id LIMIT 1) r "
                "ON r.version_id=a.version_id AND r.authority_state='APPROVED' "
                "JOIN resource_dependencies k ON k.tenant_id=r.tenant_id "
                "AND k.version_id=r.version_id AND k.relation='FIELD:relation_id' "
                "JOIN versions kind ON kind.tenant_id=k.tenant_id "
                "AND kind.resource_id=k.target_resource_id "
                "AND kind.version_id=k.target_version_id AND kind.object_type='LinkType' "
                "AND kind.identity_key=%s AND kind.authority_state='APPROVED' "
                "JOIN resource_dependencies b ON b.tenant_id=r.tenant_id "
                f"AND b.version_id=r.version_id AND b.relation='FIELD:{target}' "
                "JOIN versions t ON t.tenant_id=b.tenant_id "
                "AND t.resource_id=b.target_resource_id AND t.version_id=b.target_version_id "
                "WHERE t.authority_state='APPROVED'"
            )
            args += [request.valid_at, request.valid_at, step.name]
        if step.filters:
            ctes.append(f"unfiltered{index} AS ({sql})")
            schema_cte = f"hop_schema{index}"
            ctes.append(
                f"{schema_cte} AS (SELECT * FROM versions WHERE version_id=ANY(%s::uuid[]))"
            )
            args.append([s["version_id"] for s in stage_schemas[index]])
            checks = [
                _schema_compat_sql("candidate", schema_cte, field, args)
                for field in sorted({condition.field for condition in step.filters})
            ]
            invalid = f"invalid_hop{index}"
            ctes.append(
                f"{invalid} AS (SELECT 1 FROM unfiltered{index} candidate WHERE NOT ("
                + " AND ".join(checks)
                + ") LIMIT 1)"
            )
            invalid_stage_ctes.append((index, invalid))
            predicate = _filter_sql(step.filters, "destination", schema_cte, args, True)
            ctes.append(
                f"s{index} AS (SELECT * FROM unfiltered{index} destination WHERE true {predicate})"
            )
        else:
            ctes.append(f"s{index} AS ({sql})")
    final = f"s{len(request.traversal)}"
    ctes += [
        f"page AS (SELECT * FROM {final} ORDER BY display_name,resource_id,version_id "
        "LIMIT %s OFFSET %s)",
        f"groups AS (SELECT object_type,count(*) AS n FROM {final} GROUP BY object_type)",
    ]
    args += [request.limit, request.offset]
    sql = (
        "WITH " + ", ".join(ctes) + f" SELECT (SELECT count(*) FROM {final}), "
        "coalesce((SELECT jsonb_object_agg(object_type,n) FROM groups),'{}'::jsonb), "
        "coalesce((SELECT jsonb_agg(to_jsonb(page) - 'tenant_id' "
        "ORDER BY display_name,resource_id,version_id) FROM page),'[]'::jsonb), "
        + (
            "coalesce((SELECT jsonb_agg(to_jsonb(s)) FROM filter_schema_candidates s "
            "WHERE authority_state='APPROVED'),'[]'::jsonb)"
            if request.filters
            else "'[]'::jsonb"
        )
    )
    sql += ", " + (
        "array_remove(ARRAY["
        + ",".join(
            f"CASE WHEN EXISTS(SELECT 1 FROM {name}) THEN {index} ELSE NULL END"
            for index, name in invalid_stage_ctes
        )
        + "],NULL)"
        if invalid_stage_ctes
        else "ARRAY[]::int[]"
    )
    conn.execute("SELECT set_config('statement_timeout','10000',true)")
    try:
        row = conn.execute(sql, args).fetchone()
    except QueryCanceled as exc:
        raise WorkspaceError(
            409, "Object traversal exceeded its execution budget; no partial results returned"
        ) from exc
    assert row is not None  # Aggregate SELECT always returns one row, including empty sets.
    total, counts, objects, filter_schemas, invalid_stages = row
    if invalid_stages:
        raise WorkspaceError(
            409,
            "Reached object schema is unavailable or its property semantics "
            "differ at traversal step " + ", ".join(map(str, invalid_stages)),
        )
    for condition in request.filters:
        kinds = {
            schema["attributes"]["fields"].get(condition.field, {}).get("kind")
            for schema in filter_schemas
        }
        for kind in kinds if condition.operator != "eq" else ():
            threshold_type = {
                "integer": "numeric",
                "decimal": "numeric",
                "date": "date",
                "datetime": "timestamptz",
            }.get(kind)
            if threshold_type is None:
                continue
            representable = conn.execute(
                "SELECT pg_input_is_valid(%s,%s)",
                (str(condition.value), threshold_type),
            ).fetchone()
            if representable is None or representable[0] is not True:
                raise WorkspaceError(422, "Range threshold exceeds supported exact representation")
    schema_pins = []
    if request.filters:
        schemas = {schema["identity_key"]: schema for schema in filter_schemas}
        if set(schemas) != set(root_types):
            raise WorkspaceError(422, "Query filter schema unavailable at the requested time")
        for kind in sorted(schemas):
            schema = schemas[kind]
            validate_filters(request.filters, schema["attributes"]["fields"])
            schema_pins.append(
                FilterSchemaVersion(
                    object_type=kind,
                    resource_id=schema["resource_id"],
                    version_id=schema["version_id"],
                )
            )
        for condition in request.filters:
            if (
                condition.operator != "eq"
                and len(
                    {
                        schema["attributes"]["fields"][condition.field]["kind"]
                        for schema in schemas.values()
                    }
                )
                != 1
            ):
                raise WorkspaceError(
                    422, "Grouped range filters require the same declared field kind"
                )
    return ObjectSetResult(
        query=request,
        total=total,
        counts_by_type=counts,
        objects=objects,
        next_offset=request.offset + request.limit
        if request.offset + request.limit < total
        else None,
        filter_schema_versions=schema_pins,
        traversal_schema_versions=[
            TraversalSchemaVersion(
                step=index,
                object_type=s["identity_key"],
                resource_id=s["resource_id"],
                version_id=s["version_id"],
            )
            for index, schemas in stage_schemas.items()
            for s in schemas
        ],
    )
