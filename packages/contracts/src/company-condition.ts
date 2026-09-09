import type {CanonicalResource} from "./index.js";

export interface CompanyConditionConnection {
 record:CanonicalResource;relation:CanonicalResource;source:CanonicalResource;target:CanonicalResource;
}
export interface CompanyConditionResourceGroup {
 state:"AVAILABLE"|"EMPTY";resources:CanonicalResource[];
 coverage:"EXPLICIT_CONNECTED_RESOURCE_SNAPSHOT";reason:string;
}
export interface CompanyConditionWorkItem {
 workflow_id:string;proposal_id:string|null;company_id:string;title:string;
 state:"PREPARED"|"PENDING_REVIEW"|"PUBLISHED"|"REJECTED";
 created_at:string;reason:string;basis:"EXPLICIT_INVOCATION";
}
export interface CompanyConditionDescriptor {
 contract:"g8-company-condition/1";company:CanonicalResource;valid_at:string;known_at:string;
 connection_depth:2;connections:CompanyConditionConnection[];
 assets:CompanyConditionResourceGroup;parties:CompanyConditionResourceGroup;
 contracts:CompanyConditionResourceGroup;
 /** Required capability: absence is an unsupported server, never an empty product group. */
 products:CompanyConditionResourceGroup;
 licence_evidence:Array<{binding:CanonicalResource;notice:CanonicalResource|null;licence:CanonicalResource|null}>;
 work:{state:"AVAILABLE"|"UNAVAILABLE";reason:string|null;observed_at:string;authority:"CURRENT_RETAINED_WORK";items:CompanyConditionWorkItem[];truncated:boolean;limit:25};
 journal_reviews:CompanyJournalReviews;
 unavailable:Array<{key:"financial_performance"|"live_operations"|"findings"|"investigations"|"regulatory_compliance";label:string;reason:string}>;
 current_use_authorized:false;business_effect_authorized:false;
}

export interface CompanyJournalReviewItem {
 request_id:string;proposal_id:string;company_id:string;invocation_id:string;
 coordinate:string;title:string;state:"PREPARED"|"PENDING_REVIEW"|"PUBLISHED"|"REJECTED";
 created_at:string;reason:string;basis:"EXPLICIT_JOURNAL_PRODUCTION_REQUEST";
}
export interface CompanyJournalReviews {
 state:"AVAILABLE"|"UNAVAILABLE";reason:string|null;observed_at:string;
 authority:"CURRENT_CANONICAL_JOURNAL_REVIEW";items:CompanyJournalReviewItem[];
 truncated:boolean;limit:25;
}


/** Exact accepted definition and members; count is not a complete company inventory. */
export interface CompanyOperatingResourceGroup {
 key:string;label:string;definition:CanonicalResource;
 /** 1..201 pins, including exactly one matching definition identity/version/hash. */
 definition_pins:Array<{resource_id:string;version_id:string;content_hash:string}>;
 state:"AVAILABLE"|"EMPTY"|"UNAVAILABLE";resources:CanonicalResource[];
 valid_at:string;known_at:string;count:number|null;
 count_basis:"EXPLICIT_CONNECTED_RESOURCE_SNAPSHOT";
 completeness:"COMPLETE_WITHIN_CONNECTION_SNAPSHOT"|"UNAVAILABLE";reason:string;
}
export interface CompanyConditionDescriptorV2 extends Omit<CompanyConditionDescriptor,
 "contract"|"assets"|"parties"|"contracts"|"products"> {
 contract:"g8-company-condition/2";
 resource_groups:CompanyOperatingResourceGroup[];
 resource_groups_state:"AVAILABLE"|"UNAVAILABLE";
 resource_groups_reason:string|null;
}
