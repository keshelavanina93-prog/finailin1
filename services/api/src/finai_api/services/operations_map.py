"""Bounded, permission-filtered spatial projection of accepted ontology versions."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg.errors import QueryCanceled
from psycopg.rows import dict_row

from finai_api.domain.resources import CanonicalResource
from finai_api.domain.review import Principal
from finai_api.domain.spatial import geometry_bounds, validate_geometry
from finai_api.services import resources
from finai_api.services.workspace import WorkspaceError

SCAN_LIMIT = 5000
ASSET_TYPES = frozenset(
    {
        "Location",
        "Facility",
        "OperationalNetwork",
        "GasDistributionSystem",
        "PipelineSegment",
        "PipelineJunction",
        "Valve",
        "Regulator",
        "MeteringRegulatingStation",
        "DeliveryPoint",
        "MeteringPoint",
        "CustomerConnection",
        "GasNetworkZone",
        "PressureZone",
        "LicensedServiceArea",
        "Station",
        "Depot",
        "Tank",
        "Vehicle",
    }
)
GAS_TYPES = ASSET_TYPES - {"Facility", "Station", "Depot", "Tank", "Vehicle"}
PHYSICAL_LINKS = frozenset({"CONNECTS", "FEEDS", "SUPPLIES", "CONTROLS_OR_MEASURES"})


def snapshot(
    principal: Principal,
    valid_at: datetime | None,
    known_at: datetime | None,
    company_id: UUID | None = None,
) -> tuple[list[CanonicalResource], bool, datetime, datetime]:
    now = datetime.now(UTC)
    valid, known = valid_at or now, known_at or now
    if valid.tzinfo is None or known.tzinfo is None:
        raise WorkspaceError(422, "Historical timestamps must include a timezone")
    kinds = sorted(ASSET_TYPES | {"LegalEntity", "SpatialImport", "Relationship", "LinkType"})
    with resources.resource_connection(principal) as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT set_config('statement_timeout','10000',true)")
        try:
            # Filter immutable types before temporal selection. Scope and counts must not
            # depend on where finance rows happen to sort in an unrelated tenant inventory.
            result = cur.execute(
                """WITH RECURSIVE selected AS MATERIALIZED (
                    SELECT DISTINCT ON(v.resource_id) v.*,i.identity_key
                    FROM resource_versions v JOIN canonical_identities i
                      USING(tenant_id,resource_id)
                    WHERE v.tenant_id=%(tenant)s AND v.object_type=ANY(%(kinds)s)
                      AND i.object_type=ANY(%(kinds)s) AND v.system_from<=%(known)s
                      AND v.valid_from<=%(valid)s AND (v.valid_to IS NULL OR v.valid_to>%(valid)s)
                    ORDER BY v.resource_id,v.system_from DESC,v.version_id
                ), approved AS MATERIALIZED (
                    SELECT * FROM selected WHERE authority_state='APPROVED'
                ), roots AS (
                    SELECT resource_id::text AS resource_id FROM approved
                    WHERE resource_id=%(company)s::uuid AND object_type='LegalEntity'
                    UNION
                    SELECT r.attributes->>'target_id' FROM approved r JOIN approved kind
                      ON kind.resource_id::text=r.attributes->>'relation_id'
                    WHERE r.object_type='Relationship' AND kind.object_type='LinkType'
                      AND kind.identity_key='OPERATES'
                      AND r.attributes->>'source_id'=%(company)s::text
                ), scoped(resource_id) AS (
                    SELECT resource_id FROM roots
                    UNION
                    SELECT a.resource_id::text FROM scoped parent JOIN approved a
                      ON parent.resource_id IN (a.attributes->>'legal_entity_id',
                         a.attributes->>'system_id',a.attributes->>'network_id',
                         a.attributes->>'facility_id')
                    WHERE a.object_type=ANY(%(owned_kinds)s)
                ), included AS (
                    SELECT resource_id FROM scoped
                    UNION
                    SELECT location.resource_id::text FROM scoped owner JOIN approved a
                      ON a.resource_id::text=owner.resource_id JOIN approved location
                      ON location.resource_id::text=a.attributes->>'location_id'
                    WHERE location.object_type='Location'
                ), visible AS (
                    SELECT a.* FROM approved a WHERE %(company)s::uuid IS NULL
                      OR a.resource_id::text IN (SELECT resource_id FROM included)
                      OR a.object_type='LinkType'
                      OR (a.object_type='Relationship'
                          AND a.attributes->>'source_id' IN (SELECT resource_id FROM included)
                          AND a.attributes->>'target_id' IN (SELECT resource_id FROM included))
                ), page AS (
                    SELECT * FROM visible
                    ORDER BY (resource_id=%(company)s::uuid) DESC NULLS LAST,
                             display_name,resource_id LIMIT %(limit)s
                ) SELECT EXISTS(SELECT 1 FROM approved WHERE resource_id=%(company)s::uuid
                                AND object_type='LegalEntity') AS company_available,
                    COALESCE((SELECT jsonb_agg(to_jsonb(page)
                        ORDER BY (resource_id=%(company)s::uuid) DESC NULLS LAST,
                                 display_name,resource_id) FROM page),'[]'::jsonb) AS rows""",
                {
                    "tenant": principal.scope.tenant_id,
                    "kinds": kinds,
                    "known": known,
                    "valid": valid,
                    "company": company_id,
                    "limit": SCAN_LIMIT + 1,
                    "owned_kinds": sorted(ASSET_TYPES | {"SpatialImport"}),
                },
            ).fetchone()
        except QueryCanceled as exc:
            raise WorkspaceError(
                409,
                "Spatial snapshot exceeded its execution budget; no partial projection returned",
            ) from exc
    if company_id is not None and (not result or not result["company_available"]):
        raise WorkspaceError(404, "Company unavailable in authorized snapshot")
    rows = [CanonicalResource.model_validate(row) for row in result["rows"]] if result else []
    return rows[:SCAN_LIMIT], len(rows) > SCAN_LIMIT, valid, known


def bbox_value(raw: str | None) -> tuple[float, float, float, float] | None:
    if raw is None:
        return None
    try:
        values = [float(v) for v in raw.split(",")]
        if len(values) != 4:
            raise ValueError
        west, south, east, north = values
        validate_geometry({"type": "Point", "coordinates": [west, south]})
        validate_geometry({"type": "Point", "coordinates": [east, north]})
        if west > east or south > north:
            raise ValueError
        return west, south, east, north
    except (ValueError, TypeError) as exc:
        raise WorkspaceError(422, "bbox requires west,south,east,north in WGS84 order") from exc


def geometry_for(
    row: CanonicalResource, by_id: dict[str, CanonicalResource]
) -> tuple[dict[str, Any] | None, CanonicalResource, str | None]:
    owner = row
    if "geometry" not in row.attributes and "location_id" in row.attributes:
        location = by_id.get(str(row.attributes["location_id"]))
        if location is None or location.object_type != "Location":
            return None, row, "Location unavailable in the authorized snapshot"
        owner = location
    raw = owner.attributes.get("geometry")
    if raw is None and owner.object_type == "Location":
        lat, lon = owner.attributes.get("latitude"), owner.attributes.get("longitude")
        if lat is not None and lon is not None:
            try:
                if isinstance(lat, bool) or isinstance(lon, bool):
                    raise ValueError
                raw = {"type": "Point", "coordinates": [float(lon), float(lat)]}
            except (ValueError, TypeError):
                return None, owner, "Invalid recorded coordinates"
    if raw is None:
        return None, owner, "No accepted geometry"
    try:
        return validate_geometry(raw), owner, None
    except ValueError:
        return None, owner, "Invalid recorded geometry"


def company_scope(
    rows: list[CanonicalResource], company_id: UUID | None
) -> list[CanonicalResource]:
    if company_id is None:
        return rows
    key = str(company_id)
    by_id = {str(row.resource_id): row for row in rows}
    if key not in by_id or by_id[key].object_type != "LegalEntity":
        raise WorkspaceError(404, "Company unavailable in authorized snapshot")
    included = {key}
    for _ in range(10):
        before = len(included)
        for row in rows:
            if row.object_type not in ASSET_TYPES | {"SpatialImport"}:
                continue
            if any(
                str(row.attributes.get(field)) in included
                for field in ("legal_entity_id", "system_id", "network_id", "facility_id")
            ):
                included.add(str(row.resource_id))
        for row in rows:
            if row.object_type == "Relationship":
                relation = by_id.get(str(row.attributes.get("relation_id")))
                if (
                    relation
                    and relation.identity_key == "OPERATES"
                    and str(row.attributes.get("source_id")) == key
                ):
                    included.add(str(row.attributes.get("target_id")))
        if before == len(included):
            break
    # Locations are included only when referenced by an authorized company asset.
    for row in rows:
        if str(row.resource_id) in included:
            target = str(row.attributes.get("location_id"))
            if target in by_id and by_id[target].object_type == "Location":
                included.add(target)
    return [
        row
        for row in rows
        if str(row.resource_id) in included
        or row.object_type == "LinkType"
        or (
            row.object_type == "Relationship"
            and str(row.attributes.get("source_id")) in included
            and str(row.attributes.get("target_id")) in included
        )
    ]


def map_view(
    principal: Principal,
    lens: str = "enterprise_assets",
    bbox: str | None = None,
    valid_at: datetime | None = None,
    known_at: datetime | None = None,
    limit: int = 500,
    company_id: UUID | None = None,
) -> dict[str, Any]:
    if lens not in {"enterprise_assets", "gas_network"} or not 1 <= limit <= 1000:
        raise WorkspaceError(422, "Unsupported lens or map limit")
    bounds = bbox_value(bbox)
    rows, bounded, valid, known = snapshot(principal, valid_at, known_at, company_id)
    by_id = {str(row.resource_id): row for row in rows}
    features: list[dict[str, Any]] = []
    unmapped: list[dict[str, Any]] = []
    candidates = [
        r for r in rows if r.object_type in (GAS_TYPES if lens == "gas_network" else ASSET_TYPES)
    ]
    outside = 0
    for row in candidates:
        geometry, owner, reason = geometry_for(row, by_id)
        if geometry is None:
            unmapped.append({"resource": row.model_dump(mode="json"), "reason": reason})
            continue
        west, south, east, north = geometry_bounds(geometry)
        if bounds and (
            east < bounds[0] or north < bounds[1] or west > bounds[2] or south > bounds[3]
        ):
            outside += 1
            continue
        features.append(
            {
                "type": "Feature",
                "id": str(row.resource_id),
                "geometry": geometry,
                "properties": {
                    "resource": row.model_dump(mode="json"),
                    "geometry_resource_id": str(owner.resource_id),
                    "geometry_version_id": str(owner.version_id),
                    "observation_state": "UNAVAILABLE",
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "features": features[:limit],
        "lens": lens,
        "valid_at": valid.isoformat(),
        "known_at": known.isoformat(),
        "unmapped": unmapped[:limit],
        "counts": {
            "assets": len(candidates),
            "mapped_in_bounds": len(features),
            "outside_bounds": outside,
            "unmapped": len(unmapped),
        },
        "completeness": {
            "snapshot_bounded": bounded,
            "scan_limit": SCAN_LIMIT,
            "snapshot_scope": "COMPANY_SPATIAL_TYPES" if company_id else "AUTHORIZED_SPATIAL_TYPES",
            "features_truncated": len(features) > limit,
            "unmapped_truncated": len(unmapped) > limit,
            "limit": limit,
            "spatial_filter": "GEOMETRY_BOUNDING_BOX_INTERSECTION",
        },
        "operational_state": {
            "telemetry": "NOT_CONNECTED",
            "hydraulics": "NOT_IMPLEMENTED",
            "financial_exposure": "NOT_CONNECTED",
        },
    }


def connections(
    principal: Principal,
    resource_id: UUID,
    depth: int = 2,
    valid_at: datetime | None = None,
    known_at: datetime | None = None,
    company_id: UUID | None = None,
) -> dict[str, Any]:
    if not 1 <= depth <= 5:
        raise WorkspaceError(422, "Traversal depth must be between 1 and 5")
    rows, bounded, valid, known = snapshot(principal, valid_at, known_at, company_id)
    by_id = {str(row.resource_id): row for row in rows}
    root = str(resource_id)
    if root not in by_id:
        raise WorkspaceError(404, "Asset unavailable in authorized bounded snapshot")
    edges: list[dict[str, Any]] = []
    for row in rows:
        if row.object_type != "Relationship":
            continue
        attr = row.attributes
        relation = by_id.get(str(attr.get("relation_id")))
        name = relation.identity_key if relation and relation.object_type == "LinkType" else None
        if name not in PHYSICAL_LINKS:
            continue
        source, target = str(attr.get("source_id")), str(attr.get("target_id"))
        if source in by_id and target in by_id:
            edges.append(
                {
                    "source_id": source,
                    "target_id": target,
                    "relation": name,
                    "resource": row.model_dump(mode="json"),
                }
            )
    visited, frontier, result = {root}, {root}, []
    node_bounded = False
    for _ in range(depth):
        next_frontier: set[str] = set()
        for edge in edges:
            if edge["source_id"] not in frontier:
                continue
            target = edge["target_id"]
            if target not in visited and len(visited) >= 250:
                node_bounded = True
                continue
            result.append(edge)
            if target not in visited:
                next_frontier.add(target)
                visited.add(target)
        frontier = next_frontier
        if not frontier:
            break
    depth_bounded = any(e["source_id"] in frontier and e["target_id"] not in visited for e in edges)
    return {
        "root_id": root,
        "resources": [by_id[key].model_dump(mode="json") for key in sorted(visited)],
        "edges": result,
        "valid_at": valid.isoformat(),
        "known_at": known.isoformat(),
        "depth": depth,
        "completeness": {
            "snapshot_bounded": bounded,
            "node_bounded": node_bounded,
            "depth_bounded": depth_bounded,
            "node_limit": 250,
        },
        "interpretation": "EXPLICIT_DIRECTED_CONNECTIVITY_ONLY",
        "warning": "Connectivity is not a hydraulic or customer-impact prediction",
    }
