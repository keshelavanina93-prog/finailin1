export const epistemicStates = [
  "OBSERVED",
  "DERIVED",
  "INFERRED",
  "UNAVAILABLE",
] as const;

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
