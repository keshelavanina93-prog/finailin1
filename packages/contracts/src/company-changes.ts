import type { CanonicalResource } from "./index.js";

export interface CompanyChangesRequest {
  company_id: string;
  valid_at: string;
  known_at: string;
  compare_known_at: string;
}

export interface CompanyContextChange {
  resource_id: string;
  kind: "ADDED_TO_CONTEXT" | "REMOVED_FROM_CONTEXT" | "CHANGED_VERSION";
  before: CanonicalResource | null;
  after: CanonicalResource | null;
  /** Sorted JSON Pointer paths; empty for context membership changes. */
  changed_fields: string[];
}

export interface CompanyChangesDescriptor {
  contract: "g8-company-changes/1";
  authority: "RETAINED_COMPANY_CONTEXT_COMPARISON";
  coverage: "EXPLICIT_COMPANY_CONTEXT";
  company: CanonicalResource;
  valid_at: string;
  known_at: string;
  compare_known_at: string;
  changes: CompanyContextChange[];
  limitations: string[];
  current_use_authorized: false;
  business_effect_authorized: false;
}
