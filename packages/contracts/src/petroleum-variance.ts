export type PetroleumVarianceStatus = "RECONCILED" | "WITHIN_TOLERANCE" | "REVIEW_REQUIRED" | "EVIDENCE_MISSING" | "INVESTIGATION_OPEN" | "EXPLANATION_ACCEPTED" | "ADJUSTMENT_PROPOSED" | "APPROVAL_REQUIRED" | "RESOLVED";
export type PetroleumVariance = {
  variance_id:string; contract:"petroleum-variance/1";
  dimensions:Record<string,string>;
  physical:{opening:string;receipts:string;dispatches:string;losses:string;expected_closing:string;measured_closing:string;variance_quantity:string;variance_pct:string;equation:string};
  evidence:{source_resource_ids:string[];waybill_ids:string[];tank_dip_ids:string[];retail_sale_ids:string[];telemetry_ids:string[];source_hashes:string[];gaps:string[]};
  time:{valid_at:string|null;known_at:string|null;recorded_at:string|null;approved_at:string|null;corrected_at:string|null;replay_as_of:string|null};
  review:{status:PetroleumVarianceStatus;lifecycle:string;investigation:string;action:string;readback:string};
  financial:{status:"FINANCIAL_BRIDGED"|"FINANCIAL_BRIDGE_PARTIAL";estimated_value:string|null;valuation_basis:string|null;cogs_effect_candidate:string|null;margin_effect_candidate:string|null};
  authority:{observed:true;validated:boolean;accounting_authorized:false;business_effect_authorized:false;canonical_adjustment_created:false};
};
export type PetroleumVarianceCollection = {contract:"petroleum-variance-collection/1";company_id:string|null;rows:PetroleumVariance[];bitemporal:true;action_execution:"GOVERNED_ADAPTER_REQUIRED"};
export type PetroleumVarianceDetail = {contract:"petroleum-variance-detail/1";variance:PetroleumVariance;evidence_packet:PetroleumVariance["evidence"];lineage:Array<Record<string,unknown>>;authority:PetroleumVariance["authority"];accounting_effect:"NOT_YET_AUTHORITATIVE"};
export type PetroleumActionReadback = {contract:"petroleum-action-readback/1";adapter_id:string;external_action_id:string;readback_id:string;readback_hash:string;status:"VERIFIED"};
export type PetroleumControl = {contract:"petroleum-control/1";control_id:string;variance:PetroleumVariance;state:"INVESTIGATION_OPEN"|"EXPLANATION_ACCEPTED"|"EXPLANATION_REJECTED"|"ACTION_PROPOSED"|"APPROVED"|"REFUSED"|"READBACK_VERIFIED";events:Array<Record<string,unknown>>;initiator_actor_id:string;execution:"REFUSED_NO_EXTERNAL_ADAPTER"|"LOCAL_READBACK_VERIFIED"|"EXTERNAL_READBACK_VERIFIED";readback:PetroleumActionReadback|null;accounting_authorized:false;business_effect_authorized:false};
