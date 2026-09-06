export type AuthorityState = "OBSERVED" | "PARSED" | "MAPPED_CANDIDATE" | "VALIDATED" |
  "RECONCILED" | "APPROVED" | "AUTHORITATIVE" | "CERTIFIED" | "SUPERSEDED" | "REVOKED";

export interface VersionReference { resource_id: string; version_id: string }

export interface LifecycleRequest {
  request_id?: string;
  subject: VersionReference;
  expected_event_id?: string | null;
  target_state: AuthorityState;
  epistemic_state: "OBSERVED" | "DERIVED" | "INFERRED";
  business_state: "PROVISIONAL" | "LIVE" | "RECONCILED";
  availability_state: "AVAILABLE" | "DEGRADED" | "STALE" | "UNAVAILABLE" | "CONFLICTING";
  reason: string;
  certification_receipt_id?: string | null;
  certification_contract?: VersionReference | null;
}

export interface LifecycleReview { decision: "APPROVED" | "REJECTED"; reason: string }

export interface ConsumptionRequest {
  request_id?: string;
  consumer: VersionReference;
  inputs: VersionReference[];
  minimum_state?: AuthorityState;
}

export interface CertificationBinding {
  receipt_id: string;
  contract: VersionReference;
  proof_hash: string;
  claim: "CANONICAL_DEFINITION_CONFORMANCE";
}

export interface GuardedConsumption {
  contract_version: "guarded-consumption/2" | "guarded-consumption/3";
  consumer_certification?: CertificationBinding;
  certification_requirements?: Record<string, VersionReference>;
  upstream_authority: Array<VersionReference & { content_hash: string; access_entity: string; event_id: string | null }>;
  consumption_id: string;
  proof_hash: string;
  consumer_content_hash: string;
  consumer_event_id: string | null;
  purpose: "GUARDED_CURRENT_CONSUMPTION";
  consumer: VersionReference;
  minimum_state: AuthorityState;
  access_entity: string;
  checked_at: string;
  inputs: Array<{
    subject: VersionReference;
    event_id: string;
    content_hash: string;
    authority_state: AuthorityState;
    certification?: CertificationBinding;
    authority_control?: boolean;
    attributes: Record<string, unknown>;
    access_entity: string;
    epistemic_state: LifecycleRequest["epistemic_state"];
    business_state: LifecycleRequest["business_state"];
    availability_state: LifecycleRequest["availability_state"];
  }>;
}

export interface RollbackRequest {
  proposal_id?: string;
  versions: Record<string, string>;
  rationale: string;
  valid_from: string;
}

export interface ConsumptionStatus {
  purpose: "CONSUMPTION_ELIGIBILITY_EXPLANATION";
  consumption_id: string;
  proof_hash: string;
  current_use_authorized: false;
  status: "BLOCKED" | "RECHECK_REQUIRED";
  legacy_proof_requires_recheck: boolean;
  certification_contract_blocked?: boolean;
  checked_at: string;
  checks: Array<{
    subject: VersionReference;
    role: "CONSUMER" | "INPUT" | "UPSTREAM";
    retained_event_id: string | null;
    current_event_id: string | null;
    authority_state: AuthorityState | null;
    availability_state: LifecycleRequest["availability_state"] | null;
    event_changed: boolean;
    blocker: "CERTIFICATION_UNAVAILABLE" | "AUTHORITY_WITHDRAWN" | "AVAILABILITY_WITHDRAWN" | "MINIMUM_AUTHORITY_NOT_MET" | "VERSION_NOT_CURRENT_OR_ACCESSIBLE" | null;
  }>;
}
