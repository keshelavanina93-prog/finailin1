export type BackendWiringStatus = "strongly_wired" | "partial" | "target_only";

export type BackendRouteFamily = {
  id: string;
  label: string;
  nextProxyFamily: string | null;
  fastApiFamily: string | null;
  status: BackendWiringStatus;
  wiredRoutes: readonly string[];
  targetOnlyDimensions: readonly string[];
};

const routeFamily = (
  id: string,
  label: string,
  nextProxyFamily: string | null,
  fastApiFamily: string | null,
  status: BackendWiringStatus,
  wiredRoutes: readonly string[] = [],
  targetOnlyDimensions: readonly string[] = [],
): BackendRouteFamily => ({
  id,
  label,
  nextProxyFamily,
  fastApiFamily,
  status,
  wiredRoutes,
  targetOnlyDimensions,
});

export const BACKEND_WIRING_INVENTORY: readonly BackendRouteFamily[] = [
  routeFamily(
    "workspace",
    "Workspace, retained sources, workflows and report inputs",
    "/api/workspace",
    "/v1/workspace",
    "partial",
    [
      "/api/workspace/session -> /v1/workspace/session",
      "/api/workspace/summary -> /v1/workspace/summary",
      "/api/workspace/intake -> /v1/workspace/intake",
      "/api/workspace/workflows/* -> /v1/workspace/workflows/*",
      "/api/workspace/report-inputs -> /v1/workspace/report-inputs",
      "/api/workspace/report-calculations/* -> /v1/workspace/report-calculations/*",
      "/api/workspace/objects/* -> /v1/workspace/objects/*",
      "/api/workspace/constructions/* -> /v1/workspace/constructions/*",
    ],
    ["planning", "top-level reporting"],
  ),
  routeFamily(
    "ontology",
    "Ontology, proposals, source documents, accounting context and governed facts",
    "/api/ontology",
    "/v1/ontology",
    "strongly_wired",
    [
      "/api/ontology/source-documents/* -> /v1/ontology/source-documents/*",
      "/api/ontology/source-documents/*/accounting-context/chart-proposal -> /v1/ontology/source-documents/*/accounting-context/chart-proposal",
      "/api/ontology/account-dimension-policy -> /v1/ontology/account-dimension-policy",
      "/api/ontology/company-context -> /v1/ontology/company-context",
      "/api/ontology/model/* -> /v1/ontology/model/*",
      "/api/ontology/finance/* -> /v1/ontology/finance/*",
      "/api/ontology/proposals/* -> /v1/ontology/proposals/*",
      "/api/ontology/operator/* -> /v1/ontology/operator/*",
      "/api/ontology/history-search -> /v1/ontology/history-search",
    ],
  ),
  routeFamily(
    "operations",
    "Operations map and import proposal",
    "/api/operations",
    "/v1/operations",
    "partial",
    [
      "/api/operations/map -> /v1/operations/map",
      "/api/operations/map/*/connections -> /v1/operations/map/*/connections",
      "/api/operations/import-proposal -> /v1/operations/import-proposal",
    ],
    ["full petroleum telemetry bridge"],
  ),
  routeFamily(
    "diagnostics",
    "Diagnostic readiness and evidence context",
    "/api/diagnostics",
    "/v1/diagnostics",
    "strongly_wired",
    [
      "/api/diagnostics/readiness -> /v1/diagnostics/readiness",
      "/api/diagnostics/evidence-context -> /v1/diagnostics/evidence-context",
    ],
  ),
  routeFamily(
    "hydration",
    "Evidence and trial balance package hydration",
    "/api/hydration",
    "/v1/hydration",
    "strongly_wired",
    [
      "/api/hydration -> /v1/hydration/ingest",
      "/api/hydration/package -> /v1/hydration/trial-balance-package",
      "/api/hydration/package/diagnostics -> /v1/hydration/trial-balance-package/diagnostics",
    ],
  ),
  routeFamily(
    "readiness",
    "Frontend readiness check",
    "/api/readiness",
    "/ready",
    "strongly_wired",
    [
      "/api/readiness -> /v1/workspace/session",
      "/api/readiness -> /ready",
    ],
  ),
  routeFamily(
    "planning",
    "Planning",
    "/api/ontology/planning/catalog, /api/ontology/planning/compare",
    "/v1/ontology/planning/catalog, /v1/ontology/planning/compare",
    "partial",
    ["apps/web/app/planning-workspace.tsx"],
    ["forecast calculation, scenario proposal editor, liquidity projection, actual-vs-plan outcome"],
  ),
  routeFamily("top_level_reporting", "Top-level reporting", null, null, "target_only", [], ["top-level reporting"]),
  routeFamily(
    "nyx_reasoning",
    "NYX reasoning",
    "/api/ontology/nyx/reason",
    "/v1/ontology/nyx/reason",
    "partial",
    ["apps/web/app/nyx-interaction.tsx"],
    ["model-backed reasoning, multi-citation packets, proposal handoff execution"],
  ),
  routeFamily("outcomes_learning", "Outcomes and governed learning", null, null, "target_only", [], ["outcomes/learning"]),
  routeFamily(
    "petroleum_telemetry_bridge",
    "Full petroleum telemetry bridge",
    null,
    null,
    "target_only",
    [],
    ["full petroleum telemetry bridge"],
  ),
];

export function routeFamilyById(id: string): BackendRouteFamily | undefined {
  return BACKEND_WIRING_INVENTORY.find((family) => family.id === id);
}

export function listStronglyWiredRouteFamilies(): BackendRouteFamily[] {
  return BACKEND_WIRING_INVENTORY.filter((family) => family.status === "strongly_wired");
}

export function listPartialRouteFamilies(): BackendRouteFamily[] {
  return BACKEND_WIRING_INVENTORY.filter((family) => family.status === "partial");
}

export function listTargetOnlyRouteFamilies(): BackendRouteFamily[] {
  return BACKEND_WIRING_INVENTORY.filter((family) => family.status === "target_only");
}

export function isChartProposalWired(): boolean {
  const ontology = routeFamilyById("ontology");
  return Boolean(
    ontology?.status === "strongly_wired"
    && ontology.wiredRoutes.some((route) => route.includes("accounting-context/chart-proposal")),
  );
}
