export type PetroleumVarianceStatus = "RECONCILED" | "WITHIN_TOLERANCE" | "REVIEW_REQUIRED" | "EVIDENCE_MISSING" | "INVESTIGATION_OPEN" | "EXPLANATION_ACCEPTED" | "ADJUSTMENT_PROPOSED" | "APPROVAL_REQUIRED" | "RESOLVED";
export type PetroleumVariance = {
  variance_id:string; contract:"petroleum-variance/1";
  dimensions:Record<string,string>;
  physical:{opening:string;receipts:string;dispatches:string;losses:string;expected_closing:string;measured_closing:string;variance_quantity:string;variance_pct:string;equation:string};
  evidence:{source_resource_ids:string[];gaps:string[]};
  time:{valid_at:string|null;known_at:string|null;recorded_at:string|null;approved_at:string|null;corrected_at:string|null;replay_as_of:string|null};
  review:{status:PetroleumVarianceStatus;lifecycle:string;investigation:string;action:string;readback:string};
  financial:{status:"FINANCIAL_BRIDGE_PARTIAL";estimated_value:string|null;valuation_basis:string|null;cogs_effect_candidate:string|null;margin_effect_candidate:string|null};
  authority:{observed:true;validated:boolean;accounting_authorized:false;business_effect_authorized:false;canonical_adjustment_created:false};
};
export type PetroleumVarianceCollection = {contract:"petroleum-variance-collection/1";company_id:string|null;rows:PetroleumVariance[];bitemporal:true;action_execution:"GOVERNED_ADAPTER_REQUIRED"};
export type PetroleumControl = {contract:"petroleum-control/1";control_id:string;variance:PetroleumVariance;state:"INVESTIGATION_OPEN"|"EXPLANATION_ACCEPTED"|"EXPLANATION_REJECTED"|"ACTION_PROPOSED"|"APPROVED"|"REFUSED";events:Array<Record<string,unknown>>;initiator_actor_id:string;execution:"REFUSED_NO_EXTERNAL_ADAPTER";readback:null;accounting_authorized:false;business_effect_authorized:false};
