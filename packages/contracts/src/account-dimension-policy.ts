import type { CanonicalResource } from './ontology.js';
import type { JournalPin } from './company-journals.js';
export type JournalDimensionProvenance = {kind:'USER_ASSERTED';reason:string}|{
  kind:'REVIEWED_SOURCE_ATTRIBUTION';assignment:JournalPin;side:'DEBIT'|'CREDIT';reason:string;
};
export interface AccountDimensionPolicyResponse {
  company:CanonicalResource;chart:CanonicalResource;account:CanonicalResource;policy:CanonicalResource|null;
  state:'UNESTABLISHED'|'CURRENT'|'STALE';reason:string;rules_complete:boolean;
  rules:Array<{rule:CanonicalResource;dimension:CanonicalResource}>;checked_at:string;current_use_authorized:false;
}
export interface AccountDimensionPolicyProposalRequest {
  request_id:string;expected_version_id:string|null;company:JournalPin;chart:JournalPin;account:JournalPin;
  rules:JournalPin[];reason:string;
}
export interface AccountDimensionPolicyProposalResponse {
  proposal_id:string;policy_id:string;decision:null|'APPROVED'|'REJECTED';review_required:boolean;
}
export interface JournalDimensionReadback {
  state:'COMPLETE'|'UNESTABLISHED'|'INCOMPLETE_OR_UNAVAILABLE';policy:CanonicalResource|null;
  assignments:Array<{member:CanonicalResource;dimension:CanonicalResource;provenance:JournalDimensionProvenance}>;
  issues:string[];
}
