export const epistemicStates = [
  "OBSERVED",
  "DERIVED",
  "INFERRED",
  "UNAVAILABLE",
] as const;

export type { SchemaField, CanonicalResource, ResourceMutation, ResourceProposal, ResourceProposalDetail, ProposalSummary, CanonicalDetail, HistoricalGraph } from "./ontology.js";
export type { AuthorityState, VersionReference, LifecycleRequest, LifecycleReview, ConsumptionRequest, GuardedConsumption, RollbackRequest } from "./lifecycle.js";

export interface IngestRequest {
  scope: ExactScope;
  filename: string;
  csv_text: string;
  requested_objects?: string[];
  context_version_id?: string | null;
  account_version_ids?: Record<string, string>;
  source_system?: string | null;
  account_alias_version_ids?: Record<string, string>;
}

export interface IngestReceipt {
  binding_state: "SOURCE_ONLY" | "CANONICAL_BOUND";
  context_version_id: string | null;
  canonical_references: Record<string, { resource_id: string; version_id: string }>;
  receipt_id: string;
  request_sha256: string;
  source_sha256: string;
  source_storage?: {
    backend: "S3";
    bucket: string;
    object_key: string;
    sha256: string;
    byte_length: number;
    version_id?: string | null;
  } | null;
  scope: ExactScope;
  source_class: "TRIAL_BALANCE" | "UNFAMILIAR_TABULAR";
  authority_state: "MAPPED_CANDIDATE";
  plan: string[];
  candidates: Array<{
    object_type: string;
    source_row: number;
    epistemic_state: "OBSERVED" | "DERIVED";
    authority_state: "MAPPED_CANDIDATE";
    values: Record<string, string>;
    canonical_references: Record<string, { resource_id: string; version_id: string }>;
  }>;
  rejects: string[];
  warnings: string[];
  reconciliation: Record<string, string>;
  authority_contract_version: string;
  pack_version: string;
  used_fields: string[];
  unused_fields: string[];
  functions_executed: string[];
}

export interface Principal {
  actor_id: string;
  display_name: string;
  scope: ExactScope;
  permissions: Array<"read" | "ingest" | "review" | "export" | "ontology_read" | "ontology_propose" | "ontology_review" | "ontology_admin">;
}

export interface ReviewDecision {
  decision_id: string;
  receipt_id: string;
  decision: "APPROVED" | "REJECTED";
  actor_id: string;
  reason: string;
  previous_head: string | null;
  decided_at: string;
}

export interface IntakeItem {
  receipt_id: string;
  filename: string;
  source_class: string;
  source_sha256: string;
  submitted_by: string | null;
  ingested_at: string;
  candidate_count: number;
  reject_count: number;
  reconciliation_status: string;
  review_state: "PENDING" | "APPROVED" | "REJECTED";
  is_current: boolean;
}

export interface ReceiptDetail {
  receipt: IngestReceipt;
  filename: string;
  submitted_by: string | null;
  ingested_at: string;
  decision: ReviewDecision | null;
  current_head: string | null;
  approval_blockers: string[];
  impact: Record<"added" | "changed" | "removed" | "unchanged", number>;
}

export interface WorkspaceObject {
  canonical_references: Record<string, { resource_id: string; version_id: string }>;
  object_id: string;
  receipt_id: string;
  object_index: number;
  object_type: string;
  source_row: number;
  epistemic_state: "OBSERVED" | "DERIVED";
  authority_state: "APPROVED";
  values: Record<string, string>;
  function: string | null;
}

export interface ObjectDetail {
  object: WorkspaceObject;
  scope: ExactScope;
  source_sha256: string;
  source_row_values: Record<string, string>;
  decision: ReviewDecision;
  is_current: boolean;
}

export interface WorkspaceSummary {
  scope: ExactScope;
  pending_count: number;
  approved_count: number;
  rejected_count: number;
  active_versions: Array<{ source_class: string; receipt_id: string }>;
}

export type EpistemicState = (typeof epistemicStates)[number];
export type SourceKind = "TRIAL_BALANCE" | "GENERAL_LEDGER" | "DATABASE" | "DOCUMENT";

export interface ExactScope {
  tenant_id: string;
  legal_entity_id: string;
  period: string;
  currency: string;
}

export interface EvidenceReference {
  evidence_id: string;
  content_sha256: string;
  locator: string;
}

export interface SourceField {
  name: string;
  source_path: string;
  semantic_type?: string | null;
}

export interface SourceAuthorityContract {
  contract_id: string;
  contract_version: number;
  source_kind: SourceKind;
  scope: ExactScope;
  evidence: EvidenceReference[];
  observed_fields: SourceField[];
}

export interface RequestedField {
  name: string;
  inference_candidate?: boolean;
}

export interface DerivationRule {
  output_field: string;
  rule_id: string;
  rule_version: number;
  depends_on: string[];
}

export interface CompileHydrationRequest {
  authority_contract: SourceAuthorityContract;
  requested_fields: RequestedField[];
  derivation_rules?: DerivationRule[];
  compiler_version?: "authority-compiler/0.1";
}

export interface FieldAuthority {
  field: string;
  state: EpistemicState;
  authoritative: boolean;
  evidence_ids: string[];
  source_path?: string | null;
  rule_id?: string | null;
  rule_version?: number | null;
  dependencies: string[];
  rationale: string;
}

export interface ConstructionReceipt {
  receipt_id: string;
  compiler_version: string;
  authority_contract_id: string;
  authority_contract_version: number;
  exact_scope: ExactScope;
  request_sha256: string;
  fields: FieldAuthority[];
  promotion_state: "CANDIDATE_ONLY";
}
