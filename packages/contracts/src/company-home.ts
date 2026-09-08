import type {CanonicalResource} from "./index.js";
import type {AnalysisProjection} from "./semantic-analysis.js";
export interface CompanyHomeDescriptor {
 contract:"g8-company-home/1";
 company:CanonicalResource;company_label:string;valid_at:string;known_at:string;
 domain_packs:CanonicalResource[];analyses:AnalysisProjection[];
 operations:{lens:"gas_network"|"enterprise_assets";authority:"GEOGRAPHY_CONTEXT_ONLY";valid_at:string;known_at:string;domain_pack_ids:string[];limitation:string};
 unavailable_financials:Array<{key:"profit_loss"|"balance_sheet"|"cash_flow"|"working_capital";label:string;reason:string}>;
 current_use_authorized:false;business_effect_authorized:false;
}
