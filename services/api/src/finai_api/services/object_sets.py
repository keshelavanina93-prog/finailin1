"""Set operations over canonical identities and immutable dependency pins."""

from datetime import UTC, datetime
from typing import Any

from psycopg.types.json import Jsonb

from finai_api.domain.object_sets import FilterSchemaVersion, ObjectSetQuery, ObjectSetResult
from finai_api.domain.review import Principal
from finai_api.services.object_filter_contract import validate_filters
from finai_api.services.resources import resource_connection
from finai_api.services.workspace import WorkspaceError


def query_objects(
    principal: Principal, request: ObjectSetQuery, types: list[str] | None = None
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
    forward = all(
        step.kind == "reference" and step.direction == "outgoing" for step in request.traversal
    )
    args: list[Any] = [principal.scope.tenant_id, request.known_at]
    materialization = "NOT MATERIALIZED" if forward else "MATERIALIZED"
    ctes = [
        f"versions AS {materialization} (SELECT v.*,i.identity_key FROM resource_versions v "
        "JOIN canonical_identities i USING(tenant_id,resource_id) "
        "WHERE v.tenant_id=%s AND v.system_from<=%s)",
    ]
    if forward:
        # Types cannot change for an identity. Filter before temporal selection,
        # and constrain both sides of the RLS-protected identity/version join.
        ctes.append(
            "root_versions AS (SELECT v.*,i.identity_key FROM resource_versions v "
            "JOIN canonical_identities i USING(tenant_id,resource_id) "
            "WHERE v.tenant_id=%s AND v.system_from<=%s "
            "AND v.object_type=ANY(%s::text[]) AND i.object_type=ANY(%s::text[]))"
        )
        args += [principal.scope.tenant_id, request.known_at, root_types, root_types]
    effective_source = "root_versions" if forward else "versions"
    ctes += [
        f"effective AS (SELECT DISTINCT ON(resource_id) * FROM {effective_source} "
        "WHERE valid_from<=%s AND (valid_to IS NULL OR valid_to>%s) "
        "ORDER BY resource_id,system_from DESC,version_id)",
        "current_objects AS (SELECT * FROM effective WHERE authority_state='APPROVED')",
    ]
    args += [request.valid_at, request.valid_at, root_types]
    predicate = "object_type=ANY(%s::text[])"
    if request.resource_ids is not None:
        predicate += " AND resource_id=ANY(%s::uuid[])"
        args.append(request.resource_ids)
    for condition in request.filters:
        predicate += " AND attributes @> %s::jsonb"
        args.append(Jsonb({condition.field: condition.value}))
    predicate += " AND position(lower(%s) in lower(display_name || ' ' || identity_key))>0"
    args.append(request.search)
    ctes.append("s0 AS (SELECT * FROM current_objects WHERE " + predicate + ")")
    for index, step in enumerate(request.traversal, 1):
        previous = f"s{index - 1}"
        if step.kind == "reference":
            if step.direction == "outgoing":
                destination = (
                    "JOIN LATERAL (SELECT * FROM versions pinned "
                    "WHERE pinned.tenant_id=d.tenant_id "
                    "AND pinned.resource_id=d.target_resource_id "
                    "AND pinned.version_id=d.target_version_id LIMIT 1) t ON true "
                    if forward
                    else "JOIN versions t ON t.tenant_id=d.tenant_id "
                    "AND t.resource_id=d.target_resource_id "
                    "AND t.version_id=d.target_version_id "
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
                    "AND d.target_version_id=s.version_id AND d.relation=%s "
                    "JOIN current_objects t ON t.tenant_id=d.tenant_id "
                    "AND t.version_id=d.version_id"
                )
            args.append("FIELD:" + step.name)
        else:
            source = "source_id" if step.direction == "outgoing" else "target_id"
            target = "target_id" if step.direction == "outgoing" else "source_id"
            sql = (
                f"SELECT DISTINCT t.* FROM {previous} s "
                "JOIN resource_dependencies a ON a.tenant_id=s.tenant_id "
                f"AND a.target_version_id=s.version_id AND a.relation='FIELD:{source}' "
                "JOIN current_objects r ON r.tenant_id=a.tenant_id "
                "AND r.version_id=a.version_id AND r.object_type='Relationship' "
                "JOIN resource_dependencies k ON k.tenant_id=r.tenant_id "
                "AND k.version_id=r.version_id AND k.relation='FIELD:relation_id' "
                "JOIN versions kind ON kind.tenant_id=k.tenant_id "
                "AND kind.version_id=k.target_version_id AND kind.object_type='LinkType' "
                "AND kind.identity_key=%s AND kind.authority_state='APPROVED' "
                "JOIN resource_dependencies b ON b.tenant_id=r.tenant_id "
                f"AND b.version_id=r.version_id AND b.relation='FIELD:{target}' "
                "JOIN versions t ON t.tenant_id=b.tenant_id "
                "AND t.resource_id=b.target_resource_id AND t.version_id=b.target_version_id "
                "WHERE t.authority_state='APPROVED'"
            )
            args.append(step.name)
        ctes.append(f"s{index} AS ({sql})")
    final = f"s{len(request.traversal)}"
    if request.filters:
        ctes.append(
            "filter_schema_candidates AS (SELECT DISTINCT ON(resource_id) * FROM versions "
            "WHERE object_type='SchemaDefinition' AND identity_key=ANY(%s::text[]) "
            "AND valid_from<=%s AND (valid_to IS NULL OR valid_to>%s) "
            "ORDER BY resource_id,system_from DESC,version_id)"
        )
        args += [root_types, request.valid_at, request.valid_at]
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
    with resource_connection(principal) as conn:
        conn.execute("SELECT set_config('statement_timeout','10000',true)")
        row = conn.execute(sql, args).fetchone()
        assert row is not None  # Aggregate SELECT always returns one row, including empty sets.
        total, counts, objects, filter_schemas = row
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
    return ObjectSetResult(
        query=request,
        total=total,
        counts_by_type=counts,
        objects=objects,
        next_offset=request.offset + request.limit
        if request.offset + request.limit < total
        else None,
        filter_schema_versions=schema_pins,
    )
