import type {AnalysisPin,AnalysisProjection,RetainedAnalysisPage,RetainedAnalysisReference} from "@finai/contracts";
import {restorationInstant} from "./definition-restoration-time";
import {assertProjection} from "./semantic-analysis-state";
import {displayedAnalysisView,type SourceReviewTarget} from "./source-review-route";
const uuid=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i,hash=/^[a-f0-9]{64}$/;
const pin=(value:AnalysisPin)=>Boolean(value&&uuid.test(value.resource_id)&&uuid.test(value.version_id)&&hash.test(value.content_hash));
const exactPin=(left:AnalysisPin,right:AnalysisPin)=>left?.resource_id===right.resource_id&&left.version_id===right.version_id&&left.content_hash===right.content_hash;
const opaque=(value:unknown)=>typeof value==="string"&&value.length>0&&value.length<=4096&&!/[\s\u0000-\u001f]/.test(value);
function referenceValid(item:RetainedAnalysisReference,companyId:string):boolean {
 return Boolean(item&&uuid.test(item.invocation_id)&&pin(item.function)&&pin(item.company)&&item.company.resource_id===companyId&&typeof item.title==="string"&&item.title.trim()&&item.title.length<=512&&hash.test(item.receipt_hash)&&typeof item.run_id==="string"&&/^fcr_[a-f0-9]{64}$/.test(item.run_id)&&restorationInstant(item.valid_at)&&restorationInstant(item.known_at)&&restorationInstant(item.recorded_at)&&["semantic-analysis/1","semantic-analysis/2"].includes(item.projection_contract)&&item.eligibility==="COMPANY_SUBJECT_VERIFIED_SOURCE_REVIEW_REQUIRED");
}
export function assertRetainedAnalysisPage(value:RetainedAnalysisPage,companyId:string,expected?:{recordedBefore:string;cursor:string}):void {
 const cutoff=restorationInstant(value?.recorded_before),observed=restorationInstant(value?.observed_at);
 if(!uuid.test(companyId)||value?.purpose!=="HISTORICAL_COMPANY_ANALYSIS_DISCOVERY"||value.company_id!==companyId||!cutoff||!observed||cutoff>observed||expected&&cutoff!==restorationInstant(expected.recordedBefore)||value.coverage!=="BOUNDED_RETAINED_INVOCATION_PAGE"||value.adapter_scope!=="OBJECT_TABLES_AND_GROUPED_OBSERVATIONS_ONLY"||value.current_use_authorized!==false||value.business_effect_authorized!==false||!Array.isArray(value.items)||value.items.length>5||![value.inspected_count,value.returned_count,value.not_listed_count].every(count=>Number.isInteger(count)&&count>=0&&count<=5)||value.returned_count!==value.items.length||value.inspected_count!==value.returned_count+value.not_listed_count||value.next_cursor!==null&&(!opaque(value.next_cursor)||value.next_cursor===expected?.cursor)||value.items.some(item=>!referenceValid(item,companyId)||restorationInstant(item.recorded_at)! >cutoff)||new Set(value.items.map(item=>item.invocation_id)).size!==value.items.length)throw Error("Retained analysis discovery did not preserve this company, bounded scan and historical reference contract.");
}
export function retainedAnalysisTarget(projection:AnalysisProjection,item:RetainedAnalysisReference,companyId:string):SourceReviewTarget {
 if(!referenceValid(item,companyId))throw Error("The selected retained analysis reference is unavailable.");
 assertProjection(projection,{company_id:companyId,invocation_id:item.invocation_id});
 const d=projection.descriptor;
 if(d.contract!==item.projection_contract||d.receipt_hash!==item.receipt_hash||d.run_id!==item.run_id||!exactPin(d.function,item.function)||!exactPin(d.company,item.company)||restorationInstant(d.valid_at)!==restorationInstant(item.valid_at)||restorationInstant(d.known_at)!==restorationInstant(item.known_at)||restorationInstant(d.recorded_at)!==restorationInstant(item.recorded_at))throw Error("Source review did not reproduce the selected retained receipt, run, function, company version and times. No successor result has been substituted.");
 return {companyId,invocationId:item.invocation_id,view:displayedAnalysisView(projection,companyId)};
}
export const retainedAnalysisRequestCurrent=(request:number,current:number,signal:AbortSignal)=>request===current&&!signal.aborted;
