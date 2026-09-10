import type {CompanyFinancialResults} from "@finai/contracts";
import {metricPin,metricRecord,sameMetricPin} from "./metric-observation-state";
import {restorationInstant} from "./definition-restoration-time";
import {parseView} from "./semantic-analysis-state";
import type {FinanceReportReference} from "./finance-report-reference";

const uuid=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i,hash=/^[a-f0-9]{64}$/;
const id=(v:unknown):v is string=>typeof v==="string"&&uuid.test(v);
const digest=(v:unknown):v is string=>typeof v==="string"&&hash.test(v);
const time=(v:unknown)=>Boolean(restorationInstant(v));
function refuse():never{throw Error("The financial discovery does not match this company or its retained references. No substitute result is shown.");}
export function assertFinanceDiscovery(value:unknown,companyId:string,snapshot?:{valid_at:string;known_at:string}):asserts value is CompanyFinancialResults {
 const v=metricRecord(value),company=metricRecord(v.company);
 if(v.contract!=="company-financial-results/1"||!metricPin(company)||company.resource_id!==companyId||v.current_use_authorized!==false||v.business_effect_authorized!==false||!time(v.valid_at)||!time(v.known_at)||!time(v.catalog_checked_at))refuse();
 if(snapshot&&(restorationInstant(v.valid_at)!==restorationInstant(snapshot.valid_at)||restorationInstant(v.known_at)!==restorationInstant(snapshot.known_at)))refuse();
 if(!Array.isArray(v.sources)||!Array.isArray(v.capabilities)||!Array.isArray(v.results)||!Array.isArray(v.unavailable_capabilities)||![v.next_function_cursor,v.next_invocation_cursor].every(x=>x===null||id(x)))refuse();
 const sources=v.sources.map(metricRecord);
 for(const source of sources){const scope=metricRecord(source.scope);if(!metricPin(scope)||metricRecord(metricRecord(source.scope).attributes).legal_entity_id!==companyId||!Array.isArray(source.bindings)||!source.bindings.every(metricPin))refuse();}
 for(const raw of v.capabilities){
  const c=metricRecord(raw);
  if(!metricPin(c.function)||typeof c.display_name!=="string"||!["DISCOVERED","ACCOUNTING_BINDING_BLOCKED"].includes(String(c.state))||c.current_use_authorized!==false||c.business_effect_authorized!==false)refuse();
  if(c.kind==="SOURCE_POSTED_MOVEMENTS"){
   const source=sources.find(s=>sameMetricPin(s.scope,c.source_scope));
   if(c.required_input!=="REVIEWED_SOURCE_CONTEXT"||!source||!(source.bindings as unknown[]).some(b=>sameMetricPin(b,c.accounting_binding))||typeof c.document_id!=="string"||!digest(c.source_sha256)||typeof c.sheet!=="string")refuse();
  }else if(c.kind!=="ACCEPTED_JOURNAL_MOVEMENTS"||c.required_input!=="EXACT_ACCEPTED_MOVEMENTS_INPUT"||c.source_scope!==null||c.accounting_binding!==null)refuse();
 }
 const seen=new Set<string>();
 for(const raw of v.results){
  const r=metricRecord(raw);
  if(!id(r.invocation_id)||seen.has(r.invocation_id)||!metricPin(r.function)||!digest(r.receipt_hash)||!time(r.valid_at)||!time(r.known_at)||!time(r.recorded_at)||typeof r.run_id!=="string"||!/^fcr_[a-f0-9]{64}$/.test(r.run_id)||metricRecord(r.source).company_id!==companyId||r.state!=="RETAINED_RESULT_REFERENCE"||!["SEMANTIC_ANALYSIS","FUNCTION_HISTORY"].includes(String(r.reopen))||r.current_use_authorized!==false||r.business_effect_authorized!==false)refuse();
  seen.add(r.invocation_id);
 }
}
export type FinanceSelection={invocationId:string;receiptHash?:string};
/** Historical selection is independent of today's capability/binding catalog. */
export function financeLinkedSelection(url:URL,companyId:string,initial:FinanceReportReference|null):FinanceSelection|null {
 const reference=url.searchParams.get("finance_result");
 let selected:FinanceSelection|null=null;
 if(reference){let value:Record<string,unknown>;try{value=metricRecord(JSON.parse(reference));}catch{refuse();}if(value.companyId!==companyId||!id(value.invocationId)||value.receiptHash!==undefined&&!digest(value.receiptHash))refuse();selected={invocationId:value.invocationId,...(value.receiptHash===undefined?{}:{receiptHash:String(value.receiptHash)})};}
 const raw=url.searchParams.get("finance_analysis_view");
 if(raw){const view=parseView(raw,companyId);if(!view||view.journalSnapshot!==undefined||selected&&(selected.invocationId!==view.request.invocation_id||selected.receiptHash!==undefined&&selected.receiptHash!==view.receipt_hash))refuse();return {invocationId:view.request.invocation_id,receiptHash:view.receipt_hash};}
 if(selected)return selected;
 if(!initial)return null;
 if(initial.companyId!==companyId||!id(initial.invocationId))refuse();
 return {invocationId:initial.invocationId};
}
