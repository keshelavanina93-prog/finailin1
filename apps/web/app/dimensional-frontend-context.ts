export type DimensionalAuthorityState =
  | "unscoped"
  | "source_owned"
  | "retained_evidence"
  | "derived_candidate"
  | "approved_canonical"
  | "certified_report"
  | "ai_inference"
  | "action_approved"
  | "blocked"
  | "refused";

export type DimensionalTimeScope = {
  validAt?: string;
  knownAt?: string;
  recordedAt?: string;
  approvedAt?: string;
  replayAsOf?: string;
};

export type DimensionalFrontendContext = {
  tenantId: string;
  actorId: string;
  role: string;
  permissions: readonly string[];
  companyId?: string;
  legalEntityId?: string;
  facilityId?: string;
  stationId?: string;
  warehouseId?: string;
  ledgerId?: string;
  periodId?: string;
  currencyId?: string;
  datasetId?: string;
  sourceId?: string;
  evidenceId?: string;
  sourceHash?: string;
  ontologyVersionId?: string;
  scenarioVersionId?: string;
  authorityState: DimensionalAuthorityState;
  time: DimensionalTimeScope;
};

export type ExactScopeRequirement =
  | "tenant"
  | "actor"
  | "company"
  | "period"
  | "currency"
  | "ledger"
  | "dataset"
  | "source"
  | "evidence"
  | "valid_at"
  | "known_at";

export type ExactScopeEnvelope = {
  tenant_id: string;
  actor_id: string;
  company_id?: string;
  period_id?: string;
  currency_id?: string;
  ledger_id?: string;
  dataset_id?: string;
  source_id?: string;
  evidence_id?: string;
  valid_at?: string;
  known_at?: string;
};

const requirementFields: Record<ExactScopeRequirement, keyof ExactScopeEnvelope> = {
  tenant: "tenant_id",
  actor: "actor_id",
  company: "company_id",
  period: "period_id",
  currency: "currency_id",
  ledger: "ledger_id",
  dataset: "dataset_id",
  source: "source_id",
  evidence: "evidence_id",
  valid_at: "valid_at",
  known_at: "known_at",
};

export const financeScopeRequirements: readonly ExactScopeRequirement[] = [
  "tenant",
  "actor",
  "company",
  "period",
  "currency",
  "ledger",
  "evidence",
];

export const operationalScopeRequirements: readonly ExactScopeRequirement[] = [
  "tenant",
  "actor",
  "company",
  "source",
  "evidence",
  "valid_at",
  "known_at",
];

export function exactScopeEnvelope(context: DimensionalFrontendContext): ExactScopeEnvelope {
  return {
    tenant_id: context.tenantId,
    actor_id: context.actorId,
    company_id: context.companyId,
    period_id: context.periodId,
    currency_id: context.currencyId,
    ledger_id: context.ledgerId,
    dataset_id: context.datasetId,
    source_id: context.sourceId,
    evidence_id: context.evidenceId,
    valid_at: context.time.validAt,
    known_at: context.time.knownAt,
  };
}

export function missingScope(
  context: DimensionalFrontendContext,
  requirements: readonly ExactScopeRequirement[],
): ExactScopeRequirement[] {
  const envelope = exactScopeEnvelope(context);
  return requirements.filter((requirement) => {
    const value = envelope[requirementFields[requirement]];
    return typeof value !== "string" || value.trim().length === 0;
  });
}

export function canRequestExactScope(
  context: DimensionalFrontendContext,
  requirements: readonly ExactScopeRequirement[],
): boolean {
  return missingScope(context, requirements).length === 0 && context.authorityState !== "blocked" && context.authorityState !== "refused";
}

export function authorityLabel(state: DimensionalAuthorityState): string {
  switch (state) {
    case "unscoped":
      return "Unscoped";
    case "source_owned":
      return "Source owned";
    case "retained_evidence":
      return "Retained evidence";
    case "derived_candidate":
      return "Derived candidate";
    case "approved_canonical":
      return "Approved canonical";
    case "certified_report":
      return "Certified report";
    case "ai_inference":
      return "AI inference";
    case "action_approved":
      return "Action approved";
    case "blocked":
      return "Blocked";
    case "refused":
      return "Refused";
  }
}

export function contextSummary(context: DimensionalFrontendContext): string {
  const parts = [
    context.companyId ? `company:${context.companyId}` : "company:unscoped",
    context.periodId ? `period:${context.periodId}` : "period:unscoped",
    context.currencyId ? `currency:${context.currencyId}` : "currency:unscoped",
    authorityLabel(context.authorityState),
  ];
  return parts.join(" | ");
}
