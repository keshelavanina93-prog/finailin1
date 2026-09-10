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
      "/api/workspace/executable-preflight -> /v1/workspace/executable-preflight",
      "/api/workspace/executable-functions -> /v1/workspace/executable-functions",
      "/api/workspace/calculation/compile -> /v1/workspace/calculation/compile",
    ],
    ["forecast authoring/calculation, liquidity, and release certification"],
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
      "/api/operations/petroleum/reconciliation -> /v1/operations/petroleum/reconciliation",
      "/api/operations/petroleum/variances -> /v1/operations/petroleum/variances",
      "/api/operations/petroleum/variances/{variance_id} -> /v1/operations/petroleum/variances/{variance_id}",
      "/api/operations/petroleum/variances/investigations -> /v1/operations/petroleum/variances/investigations",
      "/api/operations/petroleum/variances/investigations/{control_id} -> /v1/operations/petroleum/variances/investigations/{control_id}",
      "/api/operations/petroleum/variances/investigations/{control_id}/decision -> /v1/operations/petroleum/variances/investigations/{control_id}/decision",
      "/api/operations/petroleum/variances/investigations/{control_id}/execute -> /v1/operations/petroleum/variances/investigations/{control_id}/execute",
      "/api/operations/petroleum/variances/investigations/{control_id}/outcome/measure -> /v1/operations/petroleum/variances/investigations/{control_id}/outcome/measure",
      "/api/operations/petroleum/margin -> /v1/operations/petroleum/margin",
      "/api/operations/petroleum/movement-journal-reconciliation -> /v1/operations/petroleum/movement-journal-reconciliation",
      "/api/operations/petroleum/telemetry -> /v1/operations/petroleum/telemetry",
      "/api/operations/petroleum/lineage/{resource_id} -> /v1/operations/petroleum/lineage/{resource_id}",
      "/api/operations/petroleum/intake/{receipt_id}/validation -> /v1/operations/petroleum/intake/{receipt_id}/validation",
      "/api/operations/petroleum/intake/{receipt_id}/promotion-preview -> /v1/operations/petroleum/intake/{receipt_id}/promotion-preview",
      "/api/operations/petroleum/intake/{receipt_id}/promotion-proposal -> /v1/operations/petroleum/intake/{receipt_id}/promotion-proposal",
    ],
    ["authentic ORPAK/SCADA connectors, external investigation/action/readback adapters"],
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
    "Evidence, structured operational JSON, and trial balance package hydration",
    "/api/hydration",
    "/v1/hydration",
    "strongly_wired",
    [
      "/api/hydration -> /v1/hydration/ingest (CSV/JSON/XLS/XLSX)",
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
    "/api/ontology/planning/catalog, /api/ontology/planning/compare, /api/ontology/planning/forecast, /api/ontology/planning/liquidity, /api/ontology/planning/proposals",
    "/v1/ontology/planning/catalog, /v1/ontology/planning/compare, /v1/ontology/planning/forecast, /v1/ontology/planning/liquidity, /v1/ontology/planning/proposals",
    "partial",
    ["apps/web/app/planning-workspace.tsx"],
    [],
  ),
  routeFamily(
    "top_level_reporting",
    "Top-level reporting",
    "/api/ontology/retained-reports/preview, /api/ontology/retained-reports, /api/ontology/retained-reports/{proposal_id}, /api/ontology/retained-reports/{proposal_id}/exports/{format}",
    "/v1/ontology/retained-reports/preview, /v1/ontology/retained-reports, /v1/ontology/retained-reports/{proposal_id}, /v1/ontology/retained-reports/{proposal_id}/exports/{format}",
    "partial",
    ["apps/web/app/reporting-workspace.tsx"],
    ["certification/release gate and broader report families remain open"],
  ),
  routeFamily(
    "nyx_reasoning",
    "NYX reasoning",
    "/api/ontology/nyx/reason",
    "/v1/ontology/nyx/reason",
    "partial",
    ["apps/web/app/nyx-interaction.tsx"],
    ["model-backed reasoning, multi-citation packets, proposal handoff execution"],
  ),
  routeFamily(
    "outcomes_learning",
    "Outcomes and governed learning",
    "/api/ontology/outcomes/actual-vs-plan, /api/ontology/outcomes/multi-baseline, /api/ontology/outcomes/learning-evaluation, /api/ontology/outcomes/measurements, /api/ontology/outcomes/learning-candidates",
    "/v1/ontology/outcomes/actual-vs-plan, /v1/ontology/outcomes/multi-baseline, /v1/ontology/outcomes/learning-evaluation, /v1/ontology/outcomes/measurements, /v1/ontology/outcomes/learning-candidates",
    "partial",
    ["services/api/src/finai_api/services/outcomes.py"],
    ["production deployment executor and policy/model mutation"],
  ),
  routeFamily(
    "petroleum_telemetry_bridge",
    "Full petroleum telemetry bridge",
    "/api/operations/petroleum/telemetry",
    "/v1/operations/petroleum/telemetry",
    "partial",
    ["/api/operations/petroleum/telemetry -> /v1/operations/petroleum/telemetry"],
    ["live connector/readback and continuous alerting remain open"],
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
