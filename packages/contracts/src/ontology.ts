export interface SchemaField {
  read_permissions?: Array<"restricted_read">;
  field_id: string; semantic_id: string; kind: string; required: boolean;
  target_type?: string | null; deprecated?: boolean;
}
export interface CanonicalResource {
  resource_id: string; version_id: string; object_type: string; identity_key: string;
  display_name: string; access_entity: string; schema_version_id: string | null;
  attributes: Record<string, unknown>; content_hash: string;
  valid_from: string; valid_to: string | null; system_from: string;
  authority_state: "APPROVED" | "REVOKED"; evidence_class: string; proposal_id: string | null;
}
export interface ResourceMutation {
  access_entity?: string | null;
  resource_id: string; expected_version_id?: string | null; object_type: string;
  identity_key: string; display_name: string; attributes: Record<string, unknown>;
  valid_from: string; valid_to?: string | null; authority_state?: "APPROVED" | "REVOKED";
  evidence_class?: string;
}
export interface ResourceProposal {
  expectations?: Array<{name: string; resource_id: string; attribute_path: string[]; expected: unknown}>;
  restores_versions?: Record<string, string>;
  proposal_id: string; title: string; rationale: string; access_entity: string; mutations: ResourceMutation[];
}
export interface SemanticDiff {
  format_version: 1; base_version_id: string | null;
  changes: Array<{ path: string; category: string; operation: "ADD" | "REMOVE" | "CHANGE";
    before: { present: boolean; value?: unknown }; after: { present: boolean; value?: unknown } }>;
}
export interface ResourceProposalDetail {
  proposal: ResourceProposal; submitted_by: string; created_at: string; decision: string | null;
  reviewed_by: string | null; review_rationale: string | null; recorded_at: string | null;
  validation: { impact: Array<{ resource_id: string; name: string; operation: string; fields_changed: string[]; semantic_diff?: SemanticDiff; compatibility?: "BACKWARD_COMPATIBLE" | "INITIAL"; semantic_changes?: Array<{ field_id: string | null; field_name: string; change: string; before: unknown; after: unknown }> }>;
    downstream_impact?: { status: "COMPLETE" | "RESTRICTED"; selection: "CURRENT_ACCEPTED_HEADS_AND_PROPOSED"; max_depth: number; max_resources: number;
      affected: Array<{root_resource_id: string; resource_id: string; version_id: string; object_type: string; display_name: string; depth: number; state: "CURRENT" | "PROPOSED"}> };
    dependency_heads: Record<string,string>; compatibility: string; identity_cycles: string };
}
export interface ProposalSummary {
  proposal_id: string; title: string; rationale: string; submitted_by: string; created_at: string;
  access_entity: string; decision: string;
}
export interface CanonicalDetail {
  resource: CanonicalResource; versions: CanonicalResource[];
  dependents: Array<{resource_id: string; version_id:string; display_name:string; object_type:string; relation:string}>;
}

export interface OperatorInspection extends CanonicalDetail {
  known_at: string;
  selection_mode: "EXACT_VERSION" | "LATEST_KNOWN";
  purpose: "HISTORICAL_INSPECTION";
  current_use_authorized: false;
  versions_truncated: boolean;
  dependents_truncated: boolean;
}
export interface HistoricalGraph {
  purpose: "HISTORICAL_LINEAGE";
  root_resource_id: string;
  root_version_id: string;
  valid_at: string;
  known_at: string;
  max_depth: number;
  max_nodes: number;
  max_edges: number;
  nodes: Array<{ resource_id: string; version_id: string; object_type: string; display_name: string; authority_state: string; valid_from: string; valid_to: string | null; system_from: string }>;
  edges: Array<{ source_version_id: string; target_version_id: string; relation: string }>;
}

export interface ProposalEvaluation {
  evaluator: string; proposal_hash: string; binding_hash: string; status: "PASS" | "FAIL";
  recorded_at: string; checks: string[]; scope: string;
}

export interface PromotionCheck {
  evaluation?: ProposalEvaluation | null;
  proposal_id: string; status: "DECIDED" | "BLOCKED" | "ELIGIBLE";
  checked_at: string; blockers: string[]; advisory: true; decision: string | null;
}
