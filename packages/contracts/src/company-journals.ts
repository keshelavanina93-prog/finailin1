import type { CanonicalResource } from './ontology.js';
import type { JournalDimensionReadback } from './account-dimension-policy.js';

export type JournalPin={resource_id:string;version_id:string};
export type JournalSelection=Record<'legal_entity_id'|'ledger_id'|'book_id'|'period_id'|'chart_id'|'currency_id'|'calendar_id',JournalPin>;
interface JournalReadback {
  selection:JournalSelection;snapshot_at:string;purpose:'CANONICAL_JOURNAL_READBACK';
  current_use_authorized:false;erp_posted:false;
}
export interface CompanyJournalListResponse extends JournalReadback {
  items:Array<{journal:CanonicalResource;accounting_binding:JournalPin;book:JournalPin}>;
  total:number;limit:number;offset:number;next_offset:number|null;
  coverage:{state:'COMPLETE'|'UNRESOLVED';unresolved_journal_count:number};
}
export interface CompanyJournalDetailResponse extends JournalReadback {
  journal:CanonicalResource;binding:CanonicalResource;
  lines:Array<{line:CanonicalResource;account:CanonicalResource;source_record:CanonicalResource;dimensions:JournalDimensionReadback}>;
  integrity:{state:'COMPLETE_BALANCED'|'INCOMPLETE_OR_UNAVAILABLE';issues:string[];
    declared_line_count:number;resolved_line_count:number;
    balance:{debit:string;credit:string;currency_id:string}|null};
  binding_eligibility:{state:string;reason?:string;checked_at:string;advisory:true;
    current_use_authorized:false;eligible_for_accounting:boolean;[key:string]:unknown};
}
