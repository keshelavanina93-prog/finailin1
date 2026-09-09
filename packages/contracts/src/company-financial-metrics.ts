/** Server-owned accepted movements. No canonical MetricDefinition publication or statements. */
import type { AnalysisPin } from './semantic-analysis.js';
import type { JournalPin, JournalSelection } from './company-journals.js';

export type FinancialMetricKey = 'debit_movement'|'credit_movement'|'net_movement';
export interface FinancialMetricRequest {
  invocation_id:string; company_id:string; snapshot_at:string;
  expected_reconciliation_sha256?:string|null; expected_result_sha256?:string|null;
}
export interface FinancialMetricRecipe {
  code:FinancialMetricKey; label:string;
  function_reference:'finance.accepted-journal-movements/v1';
  definition_authority:'CODE_DEFINED_NOT_PUBLISHED';
  operation:'ACCEPTED_DEBIT'|'ACCEPTED_CREDIT'|'DEBIT_MINUS_CREDIT'; unit:JournalPin; unit_label?:string|null;
}
export type FinancialMetricValue = {state:'VALUE';value:string}|{state:'UNAVAILABLE';value:null};
export interface FinancialMetricNode {
  key:string; parent_key:string|null; kind:'COMPANY_MOVEMENTS'|'ACCOUNT_MOVEMENTS';
  label:string; account_code:string|null; subject:AnalysisPin;
  metrics:Record<FinancialMetricKey,FinancialMetricValue>;
  source_coordinates:string[]; journal_keys:string[]; analysis_row_key:string|null;
}
export interface FinancialMetricResult {
  contract:'company-financial-metrics/1'; invocation_id:string; company_id:string; snapshot_at:string;
  display_context?:Partial<Record<'ledger_id'|'book_id'|'period_id', {reference:JournalPin;label:string|null}>>;
  selection:JournalSelection; binding:AnalysisPin; source_function:AnalysisPin;
  source_sha256:string; source_receipt_hash:string; reconciliation_receipt_hash:string;
  implementation_sha256:string; result_sha256:string;
  definitions:FinancialMetricRecipe[]; nodes:FinancialMetricNode[];
  journals:Array<{journal:JournalPin;lines:JournalPin[];dimension_policies:JournalPin[];source_coordinate:string}>;
  coverage:{state:'UNAVAILABLE'|'PARTIAL'|'RECONCILED';source_rows:number;literal_source_rows:number;
    accepted_journals:number;unmatched_source_rows:number;excluded_source_rows:number;rejected_journals:number;
    missing_coordinates:string[];excluded_rows:Array<Record<string,unknown>>;rejected:Array<Record<string,unknown>>;
    ledger_completeness:'UNESTABLISHED'};
  hierarchy_basis:'COMPANY_AND_EXACT_LOCAL_ACCOUNT'; aggregation:'SERVER_OWNED_VALUES_DO_NOT_SUM_HIERARCHY';
  unavailable:string[];current_use_authorized:false;business_effect_authorized:false;
}
