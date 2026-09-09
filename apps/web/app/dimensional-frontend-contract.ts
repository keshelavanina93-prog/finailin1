export type DimensionalAxis =
  | "product_mode"
  | "user_role"
  | "business_scope"
  | "financial_scope"
  | "operational_scope"
  | "evidence_state"
  | "authority_state"
  | "time_state"
  | "interaction_projection"
  | "runtime_state"
  | "backend_contract_state"
  | "trust_zone"
  | "decision_state"
  | "acceptance_gate";

export type WiringEvidence =
  | "ui_route"
  | "context_inherited"
  | "next_proxy_allowlist"
  | "fastapi_route"
  | "domain_service"
  | "exact_scope_request"
  | "typed_contract"
  | "state_machine"
  | "authority_visible"
  | "evidence_or_lineage"
  | "approval_boundary"
  | "negative_authority_test"
  | "browser_proof"
  | "restart_readback";

export type WiringStatus = "strongly_anchored" | "partial" | "target_only";

export type DimensionalSurface = {
  id: string;
  label: string;
  productModes: string[];
  axes: DimensionalAxis[];
  frontendAnchors: string[];
  proxyRoutes: string[];
  backendRoutes: string[];
  requiredEvidence: WiringEvidence[];
  presentEvidence: WiringEvidence[];
  status: WiringStatus;
  remaining: string[];
};

export const DIMENSIONAL_AXES: readonly DimensionalAxis[] = [
  "product_mode",
  "user_role",
  "business_scope",
  "financial_scope",
  "operational_scope",
  "evidence_state",
  "authority_state",
  "time_state",
  "interaction_projection",
  "runtime_state",
  "backend_contract_state",
  "trust_zone",
  "decision_state",
  "acceptance_gate",
];

export const FULL_WIRING_EVIDENCE: readonly WiringEvidence[] = [
  "ui_route",
  "context_inherited",
  "next_proxy_allowlist",
  "fastapi_route",
  "domain_service",
  "exact_scope_request",
  "typed_contract",
  "state_machine",
  "authority_visible",
  "evidence_or_lineage",
  "approval_boundary",
  "negative_authority_test",
  "browser_proof",
  "restart_readback",
];

const coreAxes: DimensionalAxis[] = [
  "product_mode",
  "user_role",
  "business_scope",
  "evidence_state",
  "authority_state",
  "time_state",
  "interaction_projection",
  "runtime_state",
  "backend_contract_state",
  "trust_zone",
  "acceptance_gate",
];

function surface(
  id: string,
  label: string,
  productModes: string[],
  frontendAnchors: string[],
  proxyRoutes: string[],
  backendRoutes: string[],
  presentEvidence: WiringEvidence[],
  remaining: string[],
  extraAxes: DimensionalAxis[] = [],
): DimensionalSurface {
  const axes = [...new Set([...coreAxes, ...extraAxes, "decision_state"])] as DimensionalAxis[];
  const missing = FULL_WIRING_EVIDENCE.filter((gate) => !presentEvidence.includes(gate));
  const status: WiringStatus =
    missing.length === 0 ? "strongly_anchored" : presentEvidence.length >= 8 ? "partial" : "target_only";
  return {
    id,
    label,
    productModes,
    axes,
    frontendAnchors,
    proxyRoutes,
    backendRoutes,
    requiredEvidence: [...FULL_WIRING_EVIDENCE],
    presentEvidence,
    status,
    remaining: remaining.length ? remaining : missing,
  };
}

export const DIMENSIONAL_SURFACES: readonly DimensionalSurface[] = [
  surface(
    "identity_session",
    "Identity and session",
    ["command_overview"],
    ["apps/web/app/g8-workspace.tsx"],
    ["/api/workspace/session", "/api/readiness"],
    ["/v1/workspace/session", "/ready"],
    [
      "ui_route",
      "context_inherited",
      "next_proxy_allowlist",
      "fastapi_route",
      "domain_service",
      "exact_scope_request",
      "state_machine",
      "authority_visible",
      "negative_authority_test",
    ],
    ["browser_proof", "restart_readback"],
  ),
  surface(
    "source_evidence_intake",
    "Massive source evidence intake",
    ["source_intake"],
    ["apps/web/app/evidence-intake.tsx", "apps/web/app/source-documents.tsx", "apps/web/app/receipt-panel.tsx"],
    ["/api/hydration", "/api/ontology/source-documents/*", "/api/workspace/constructions/*"],
    ["/v1/hydration/ingest", "/v1/ontology/source-documents/*", "/v1/workspace/constructions/*"],
    [
      "ui_route",
      "context_inherited",
      "next_proxy_allowlist",
      "fastapi_route",
      "domain_service",
      "exact_scope_request",
      "state_machine",
      "authority_visible",
      "evidence_or_lineage",
      "negative_authority_test",
    ],
    ["typed_contract", "browser_proof", "restart_readback"],
    ["business_scope"],
  ),
  surface(
    "accounting_dimensions",
    "1C/SAP accounting dimensions",
    ["accounting"],
    [
      "apps/web/app/source-accounting-setup.tsx",
      "apps/web/app/source-accounting-context.tsx",
      "apps/web/app/source-account-bindings.tsx",
      "apps/web/app/account-dimension-policy-workbench.tsx",
    ],
    ["/api/ontology/source-documents/*/accounting-context/*", "/api/ontology/account-dimension-policy"],
    ["/v1/ontology/source-documents/*/accounting-context/*", "/v1/ontology/account-dimension-policy"],
    [
      "ui_route",
      "context_inherited",
      "next_proxy_allowlist",
      "fastapi_route",
      "domain_service",
      "exact_scope_request",
      "typed_contract",
      "state_machine",
      "authority_visible",
      "evidence_or_lineage",
      "approval_boundary",
      "negative_authority_test",
    ],
    ["browser_proof", "restart_readback"],
    ["financial_scope"],
  ),
  surface(
    "finance_ledger",
    "Finance, ledger and trial balance",
    ["accounting", "reporting"],
    ["apps/web/app/finance-workspace.tsx", "apps/web/app/trial-balance-review.tsx", "apps/web/app/company-journal-explorer.tsx"],
    ["/api/hydration/package", "/api/ontology/finance/*", "/api/ontology/company-journals/*"],
    ["/v1/hydration/trial-balance-package", "/v1/ontology/finance/*", "/v1/ontology/company-journals/*"],
    [
      "ui_route",
      "context_inherited",
      "next_proxy_allowlist",
      "fastapi_route",
      "domain_service",
      "exact_scope_request",
      "typed_contract",
      "state_machine",
      "authority_visible",
      "evidence_or_lineage",
      "approval_boundary",
      "negative_authority_test",
    ],
    ["browser_proof", "restart_readback"],
    ["financial_scope"],
  ),
  surface(
    "operations_physical_graph",
    "Operations and physical movement graph",
    ["operations"],
    ["apps/web/app/operations-map.tsx", "apps/web/app/operations-canvas.tsx", "apps/web/app/posted-movement-report.tsx"],
    ["/api/operations/*", "/api/ontology/operations/*"],
    ["/v1/operations/*", "/v1/ontology/operations/*"],
    [
      "ui_route",
      "context_inherited",
      "next_proxy_allowlist",
      "fastapi_route",
      "domain_service",
      "exact_scope_request",
      "state_machine",
      "authority_visible",
      "evidence_or_lineage",
    ],
    ["typed_contract", "approval_boundary", "negative_authority_test", "browser_proof", "restart_readback"],
    ["operational_scope"],
  ),
  surface(
    "bitemporal_lineage",
    "Bitemporal lineage and replay",
    ["investigation", "governance"],
    ["apps/web/app/operator-trace.tsx", "apps/web/app/canonical-trace.tsx", "apps/web/app/history-explorer.tsx"],
    ["/api/ontology/operator/*", "/api/ontology/history-search", "/api/ontology/event-time/*"],
    ["/v1/ontology/operator/*", "/v1/ontology/history-search", "/v1/ontology/event-time/*"],
    [
      "ui_route",
      "context_inherited",
      "next_proxy_allowlist",
      "fastapi_route",
      "domain_service",
      "exact_scope_request",
      "typed_contract",
      "state_machine",
      "authority_visible",
      "evidence_or_lineage",
      "negative_authority_test",
    ],
    ["browser_proof", "restart_readback"],
  ),
  surface(
    "nyx_reasoning",
    "NYX scoped reasoning",
    ["investigation"],
    ["apps/web/app/nyx-interaction.tsx"],
    ["/api/ontology/nyx/reason"],
    ["/v1/ontology/nyx/reason"],
    [
      "ui_route",
      "context_inherited",
      "next_proxy_allowlist",
      "fastapi_route",
      "domain_service",
      "exact_scope_request",
      "typed_contract",
      "state_machine",
      "authority_visible",
      "evidence_or_lineage",
      "approval_boundary",
      "negative_authority_test",
    ],
    [
      "model-backed reasoning",
      "multi-citation packets",
      "proposal handoff execution",
      "browser_proof",
      "restart_readback",
    ],
  ),
  surface(
    "outcomes_learning",
    "Outcomes and governed learning",
    ["outcome_learning"],
    ["apps/web/app/planning-workspace.tsx", "apps/web/app/outcome-measurement-panel.tsx"],
    ["/api/ontology/outcomes/actual-vs-plan", "/api/ontology/outcomes/learning-evaluation"],
    ["/v1/ontology/outcomes/actual-vs-plan", "/v1/ontology/outcomes/learning-evaluation"],
    [
      "ui_route",
      "context_inherited",
      "next_proxy_allowlist",
      "fastapi_route",
      "domain_service",
      "exact_scope_request",
      "typed_contract",
      "state_machine",
      "authority_visible",
      "negative_authority_test",
    ],
    [
      "evidence_or_lineage",
      "approval_boundary",
      "browser_proof",
      "restart_readback",
      "learning candidate promotion/rollback",
      "outcome timeline UI",
    ],
  ),
];

export function surfaceById(id: string): DimensionalSurface | undefined {
  return DIMENSIONAL_SURFACES.find((candidate) => candidate.id === id);
}

export function missingWiringEvidence(surfaceId: string): WiringEvidence[] {
  const found = surfaceById(surfaceId);
  if (!found) return [...FULL_WIRING_EVIDENCE];
  return found.requiredEvidence.filter((gate) => !found.presentEvidence.includes(gate));
}

export function isFullyWired(surfaceId: string): boolean {
  return missingWiringEvidence(surfaceId).length === 0;
}

export function dimensionalCoverageSummary() {
  return {
    axes: DIMENSIONAL_AXES.length,
    surfaces: DIMENSIONAL_SURFACES.length,
    fullyWired: DIMENSIONAL_SURFACES.filter((candidate) => isFullyWired(candidate.id)).length,
    partial: DIMENSIONAL_SURFACES.filter((candidate) => candidate.status === "partial").length,
    targetOnly: DIMENSIONAL_SURFACES.filter((candidate) => candidate.status === "target_only").length,
  };
}
