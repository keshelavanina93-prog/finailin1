# G8 Operations & Maps: Linear verification and Palantir research

Research date: 2026-09-05. This is an implementation brief, not delivered map capability. No Linear issues were modified.

## Verified program scope

NIN-36 (Urgent, Backlog) already defines the ontology-driven geospatial operations control plane. It includes versioned OperationalLensDefinition resources, twelve initial operational lenses, observations/events/incidents, deterministic severity, bounded impact propagation, emergency focus, governed actions and historical replay. MapLibre GL JS is already the initial renderer decision. Its latency budgets are targets, not measured performance: resident lens response p95 250 ms, fetched lens fully settled p95 2 seconds, accepted live delta visible p95 2 seconds.

NIN-37 (Backlog) supplies gas-specific physical topology, pressure/flow observations, valves, metering/regulation, customer connections, licensed areas and interruptions. NIN-25 binds cross-surface selection and business-facing map interactions. NIN-27 and NIN-35 (In Progress) govern authority and historical reconstruction. NIN-45 binds persistent investigations and financial/operational reasoning. These are semantic dependencies from the descriptions; the available connector did not expose issue blocker relations, so no claim that NIN-36 is fully unblocked is made.

The older Enterprise Hydration document says global selectors remain visible; the later NIN-25 explicitly permits contextual/hidden controls while retaining state. Use the later surface-specific interaction requirement, consistent with the approved G8 shell.

Linear: [NIN-36](https://linear.app/g8flospace/issue/NIN-36/build-ontology-driven-real-time-geospatial-operations-control-plane), [NIN-37](https://linear.app/g8flospace/issue/NIN-37/build-georgian-regulated-natural-gas-distribution-market-and), [NIN-25](https://linear.app/g8flospace/issue/NIN-25/build-the-unified-g8-operator-visual-system-graph-canvases-and-command).

## Current repository evidence

services/api/src/finai_api/domain/ontology_catalog.py has Location optional latitude/longitude, Facility location references, OperationalNetwork, GasDistributionSystem, PipelineSegment and company/operator/licence links. These are definitions, not connected GIS/network data. PipelineSegment currently has code and system_id, without junction endpoints or geometry. Generic canonical proposal/version/history and dependency-impact infrastructure exists in services/resources.py and related services. Its proposal dependency impact must not be presented as physical gas-flow propagation.

Search of apps, packages and services found no MapLibre/PostGIS implementation, spatial intersection API, GeoJSON service, OperationalLensDefinition, SeverityPolicy or operational observation/event engine. ExecutiveOverview honestly displays unavailable operating signals. The operational map therefore needs backend implementation, not merely enabling its navigation button.

## Lessons from Palantir's public product documentation

Foundry Map projects ontology objects into geography. It supports object, link, overlay and annotation layers, spatial search and connected exploration. [Map overview](https://www.palantir.com/docs/foundry/map), [core concepts](https://www.palantir.com/docs/foundry/map/core-concepts).

Search Around follows typed relationships or functions. Intermediary objects such as contracts/deliveries can explain links; function results can include related objects, edges and time-series measures. G8 should preserve these explanations, not just draw unexplained arcs. [Search Around integration](https://www.palantir.com/docs/foundry/map/integrate-searcharounds).

Time selection, live mode, playback, events and tracks make time an analysis dimension. G8 additionally requires the recorded network version for historical incidents, not today's topology. [Timeline](https://www.palantir.com/docs/foundry/map/timeline).

Drawn points, lines and polygons can initiate ontology Actions. G8 should route proposals through its own permissions/review/receipt authority; map editing cannot silently change accepted assets. [Map Actions](https://www.palantir.com/docs/foundry/map/actions).

Workshop connects map object sets and selections to the surrounding application. Its current Map widget is documented as desktop/WebGL optimized with no mobile support; G8 must explicitly validate its own mobile/table fallback. [Workshop map](https://www.palantir.com/docs/foundry/workshop/widgets-map).

Palantir documents feature tradeoffs for tiled loading: time-series styling, Search Around and timeline/histogram filtering are limited. Recommendation: use broad tiled geography plus a bounded detailed investigation overlay and independent server queries for affected objects; never silently omit affected assets because they are off-screen or clustered. [Loading methods](https://www.palantir.com/docs/foundry/map/objects-loading-methods).

Gaia is Gotham's geospatial application with separate Foundry integration options, not simply another name for Foundry Map. Its published integration methods have different refresh/scale characteristics. No Palantir scale number is a G8 performance promise. [Gaia integration](https://www.palantir.com/docs/foundry/geospatial/add-ontology-data-to-gaia).

## Recommended G8 implementation contract

1. Source onboarding: retain original GIS/asset exports, coordinate system, source date, licence/access rules and asset identifiers; validate geometry, coordinate range, missing locations and duplicate identities. Unknown locations stay visibly unmapped. Public basemaps do not establish private pipe topology.
2. Spatial authority: retain versioned geometry linked to canonical objects; use PostgreSQL plus PostGIS for spatial indexing/query projections, subject to migration review. Record original CRS and transform explicitly to the renderer's coordinate convention. Basemap providers must not receive private asset payloads. [PostGIS spatial data management](https://postgis.net/docs/using_postgis_dbmanagement.html).
3. Physical topology: directed typed connections, junctions, valves, pressure zones, supplies/serves relations and operational state. Nearby/crossing lines are not necessarily connected. Model paths and isolation reachability separately from calibrated hydraulic predictions; do not claim pressure prediction without the required model and measurements.
4. Scoped map query: exact company/access filtering before tiles, counts, search, traversal and caching. Cache keys include permission scope, lens/version and time. Return canonical IDs, effective/known-at version, evidence links, freshness and completeness.
5. Live state: timestamped unit-aware observations, event/processing time, stale thresholds, ordering, deduplication and reconnect/backfill. Keep last-known values visibly stale. Select polling/SSE/broker transport based on measured demand, without creating map-only truth.
6. Investigation: one selected object and persistent investigation across Home thumbnail, full map, network diagram, table, NYX, evidence and action review. Lenses alter emphasis without destroying selection, time, viewport or incident context.
7. Impact and severity: bounded versioned topology traversal with explicit valve/direction rules; explain affected paths, uncertainty and omitted/unknown topology. Financial exposure references approved financial functions and stays unavailable where evidence is missing. Keep consequential field/control actions behind existing authorization.
8. Performance: retain the map instance, update dynamic state incrementally, simplify/cluster wide views and load detailed selected-object data on demand. Benchmark NIN-36 targets with an explicitly declared load, and test degraded network/WebGL behavior. [MapLibre large-data guidance](https://maplibre.org/maplibre-gl-js/docs/guides/large-data/).

## Required first complete operator journey

Accepted GIS/network evidence -> select a company and station/segment -> see its geography and typed connections -> inspect pressure/flow freshness -> open a controlled anomaly -> reveal affected customers/assets and reasons -> continue the same investigation in NYX -> propose authorized response -> independent review/receipt -> replay the incident with the original topology and evidence.

Acceptance includes real retained asset geometry and controlled labelled events, tenant-denial tests for tiles/counts/traversal, no hidden affected objects on lens/zoom changes, stale-feed and reconnect behavior, historical topology correction, keyboard/table access and measured lens/update budgets. A rendered basemap alone does not satisfy NIN-36.

## Implemented foundation — 2026-09-05

Home now embeds the same MapLibre geographic canvas used by Operations & Maps. Enterprise-assets and gas-network lenses retain viewport; the map survives lens updates and resizes with the NYX rail. Asset/table selection pins the canonical resource version and effective/known timestamps in NYX. Explain selected reports recorded evidence and explicitly refuses unsupported operating/impact conclusions. Historical snapshots, bounded area queries, table filtering, reviewed/unmapped counts, and directed connection inspection are available.

Authenticated `/v1/operations/map`, `/map/{id}/connections`, and `/import-proposal` preserve tenant/entity access and optionally narrow to an accepted company. Querying scans at most 5,000 authorized resources and reports feature, unmapped, snapshot and traversal limits. Geometry bounds filtering is bounding-box intersection, not exact polygon intersection. This is not spatial-index or scale certification.

GeoJSON onboarding accepts up to 99 WGS84 Point/LineString/Polygon features, with `properties.name` and unique `properties.code`. The canonical submitted document and its canonical-JSON SHA256 are retained in a SpatialImport alongside Location proposals. Import does not retain original file bytes and does not establish pipe connectivity. Pending locations remain invisible until independent approval; evidence remains USER_ASSERTED. An accepted company and ontology proposal permission are required.

For an existing deployment, load the D:-only environment, run `scripts/install-ontology.py`, then `scripts/upgrade-spatial-catalog.py` before restarting API. The latter adds optional fields while preserving customized definitions and historical versions. No new DDL is needed.

The default public geographic context is OpenFreeMap Dark with provider attribution retained. `NEXT_PUBLIC_G8_MAP_STYLE` can point to an organization-hosted MapLibre style at build time. No private features or bearer credentials are sent with basemap requests; providers receive normal basemap viewport/tile requests. Private geometry is rendered from the authenticated local API response. WebGL/style failure leaves the asset table usable.

Validation: 12 spatial backend tests plus 21 schema-compatibility tests passed; 10 frontend tests, TypeScript, lint and production build passed. Browser checks covered the authentic empty operator scope, basemap rendering, zoom/area filtering, historical dates, gas lens, folding/resizing and narrow viewport. Populated import/approval/history/isolation was proven with isolated PostgreSQL test fixtures, not authentic company GIS or a populated browser journey.

Still open in NIN-36/NIN-37: authentic network source onboarding and populated browser acceptance; complete operational ontology and source-backed topology; ordered observations and freshness; incidents/severity; isolation/hydraulic/customer and financial impact; controlled field actions; incident replay; spatial indexing/tiles and measured production load targets. The basemap and foundation do not establish full operational readiness.
