import type {CanonicalResource} from "./index.js";

type Pin={resource_id:string;version_id:string;content_hash:string};
/** Discovery supplies references and eligibility, never computed financial values. */
export interface CompanyFinancialResults {
 contract:"company-financial-results/1";
 company:CanonicalResource;
 valid_at:string;known_at:string;catalog_checked_at:string;
 sources:Array<{scope:CanonicalResource;bindings:CanonicalResource[];binding_eligibility?:Record<string,{state:string;reason:string;checked_at:string|null;eligible_for_accounting:boolean;advisory:true;current_use_authorized:false}>}>;
 capabilities:Array<{
  function:Pin;display_name:string;implementation_id:string;
  kind:"SOURCE_POSTED_MOVEMENTS"|"ACCEPTED_JOURNAL_MOVEMENTS";
  state:"DISCOVERED"|"ACCOUNTING_BINDING_BLOCKED";reason:string|null;
  source_scope:Pin|null;accounting_binding:Pin|null;
  document_id:string|null;source_sha256:string|null;sheet:string|null;
  required_input:"REVIEWED_SOURCE_CONTEXT"|"EXACT_ACCEPTED_MOVEMENTS_INPUT";
  current_use_authorized:false;business_effect_authorized:false;
 }>;
 unavailable_capabilities:Array<{function:{resource_id:string;version_id:string};state:"UNAVAILABLE";reason:string}>;
 results:Array<{
  invocation_id:string;function:Pin;implementation_id:string;receipt_hash:string;recorded_at:string;
  run_id:string;valid_at:string;known_at:string;
  source:{company_id:string;document_id?:string;sha256?:string;sheet?:string;scope?:Pin;binding?:Pin;context?:Record<string,unknown>;selection?:Record<string,unknown>;observed_from?:string;observed_through?:string;source_invocation_id?:string;source_invocation_receipt_hash?:string;source_receipt_hash?:string;reconciliation_receipt_hash?:string;result_sha256?:string;source_valid_at?:string;source_known_at?:string;journal_observed_at?:string};
  state:"RETAINED_RESULT_REFERENCE";reopen:"SEMANTIC_ANALYSIS"|"FUNCTION_HISTORY";
  current_use_authorized:false;business_effect_authorized:false;
 }>;
 next_function_cursor:string|null;next_invocation_cursor:string|null;
 current_use_authorized:false;business_effect_authorized:false;
}
