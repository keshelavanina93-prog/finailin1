import type { CanonicalResource } from './ontology.js';
import type { JournalSelection } from './company-journals.js';

export interface PeriodControlResponse {
  selection:JournalSelection;control:CanonicalResource|null;state:'OPEN'|'LOCKED'|'UNESTABLISHED';
  reason:string;checked_at:string;current_use_authorized:false;financial_close_certified:false;erp_posted:false;
}
export interface PeriodControlProposalRequest {
  selection:JournalSelection;request_id:string;expected_version_id:string|null;
  state:'OPEN'|'LOCKED';reason:string;
}
export interface PeriodControlProposalResponse {
  proposal_id:string;control_id:string;decision:null|'APPROVED'|'REJECTED';review_required:boolean;
}
