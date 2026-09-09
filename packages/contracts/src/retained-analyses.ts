import type {AnalysisPin} from "./semantic-analysis.js";

export interface RetainedAnalysisReference {
 invocation_id:string;function:AnalysisPin;company:AnalysisPin;title:string;
 receipt_hash:string;run_id:string;valid_at:string;known_at:string;recorded_at:string;
 projection_contract:"semantic-analysis/1"|"semantic-analysis/2";
 eligibility:"COMPANY_SUBJECT_VERIFIED_SOURCE_REVIEW_REQUIRED";
}
export interface RetainedAnalysisPage {
 purpose:"HISTORICAL_COMPANY_ANALYSIS_DISCOVERY";company_id:string;
 observed_at:string;recorded_before:string;items:RetainedAnalysisReference[];
 inspected_count:number;returned_count:number;not_listed_count:number;next_cursor:string|null;
 coverage:"BOUNDED_RETAINED_INVOCATION_PAGE";
 adapter_scope:"OBJECT_TABLES_AND_GROUPED_OBSERVATIONS_ONLY";
 current_use_authorized:false;business_effect_authorized:false;
}
