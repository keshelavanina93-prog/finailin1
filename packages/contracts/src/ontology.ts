export interface SchemaField {
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
  resource_id: string; expected_version_id?: string | null; object_type: string;
  identity_key: string; display_name: string; attributes: Record<string, unknown>;
  valid_from: string; valid_to?: string | null; authority_state?: "APPROVED" | "REVOKED";
  evidence_class?: string;
}
export interface ResourceProposal {
  proposal_id: string; title: string; rationale: string; access_entity: string; mutations: ResourceMutation[];
}
export interface ResourceProposalDetail {
  proposal: ResourceProposal; submitted_by: string; created_at: string; decision: string | null;
  reviewed_by: string | null; review_rationale: string | null; recorded_at: string | null;
  validation: { impact: Array<{ resource_id: string; name: string; operation: string; fields_changed: string[] }>;
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
