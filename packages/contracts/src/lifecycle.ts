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
}

export interface LifecycleReview { decision: "APPROVED" | "REJECTED"; reason: string }

export interface ConsumptionRequest {
  consumer: VersionReference;
  inputs: VersionReference[];
  minimum_state?: AuthorityState;
}

export interface GuardedConsumption {
  purpose: "GUARDED_CURRENT_CONSUMPTION";
  consumer: VersionReference;
  minimum_state: AuthorityState;
  access_entity: string;
  checked_at: string;
  inputs: Array<{
    subject: VersionReference;
    event_id: string;
    authority_state: AuthorityState;
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
