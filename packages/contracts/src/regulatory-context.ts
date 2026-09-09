import type {CanonicalResource} from "./index.js";

/** Existing rules API read without a supplied activity or customer scenario. */
export type CompanyRegulationPage={company:{resource_id:string;version_id:string;display_name:string};at:string;known_at:string;
 context_basis:"INCOMPLETE_CONTEXT";activity:null;accounting_effects_created:false;next_offset:number|null;
 rules:Array<{resource:CanonicalResource;dependencies:Record<string,{resource_id:string;version_id:string}>;
 assessment:{legal_state:string;applicability:string;effective_obligation:boolean;obligation:string;days_to_deadline:number|null;blocking_reasons:string[]}}>};
