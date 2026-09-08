import type {AnalysisProjection,AnalysisRequest,AnalysisPin} from "@finai/contracts";
import {assertProjection,type AnalysisView} from "./semantic-analysis-state";

type Scope={companyId:string;invocationId:string};
export type ReadySourceReviewContext=Scope&{status:"ready";title:string;descriptorSha256:string;receiptHash:string;validAt:string;knownAt:string;authority:string;returnedRows:number;totalRows:number;rowKey:string|null;rowLabel:string|null;contributorIndex:number|null;contributorCount:number;excludedIndex:number|null;evidenceBasis:string|null;reference:AnalysisPin|null};
export type SourceReviewContext=ReadySourceReviewContext|Scope&{status:"updating"|"unavailable"};
const uuid=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i,hash=/^[a-f0-9]{64}$/;
export function sourceReviewContext(projection:AnalysisProjection|null,request:AnalysisRequest,state:{ready:boolean;busy:boolean;error:boolean;saved?:AnalysisView|null;excludedIndex:number|null}):SourceReviewContext {
 const scope={companyId:request.company_id,invocationId:request.invocation_id};
 if(!state.ready||state.busy)return {...scope,status:"updating"};
 if(state.error||!projection)return {...scope,status:"unavailable"};
 try{
  assertProjection(projection,request,state.saved);
  const d=projection.descriptor,selected=projection.rows.find(row=>row.key===request.selected_row);
  if(!hash.test(d.receipt_hash))throw Error("Receipt reference is unavailable.");
  const excluded=state.excludedIndex===null?null:d.excluded_evidence?.[state.excludedIndex];
  if(state.excludedIndex!==null&&!excluded)throw Error("Excluded evidence is unavailable.");
  const contributor=excluded??projection.selection?.contributor;
  const pin=contributor?.reference??selected?.trace??d.function;
  const reference=pin&&uuid.test(pin.resource_id)&&uuid.test(pin.version_id)&&hash.test(pin.content_hash)?{resource_id:pin.resource_id,version_id:pin.version_id,content_hash:pin.content_hash}:null;
  return {...scope,status:"ready",title:d.title?.slice(0,300)??"Source review",descriptorSha256:projection.descriptor_sha256,receiptHash:d.receipt_hash,validAt:d.valid_at,knownAt:d.known_at,authority:d.authority?.slice(0,120)??"Authority unavailable",returnedRows:projection.rows.length,totalRows:projection.total_rows,rowKey:excluded?null:selected?.key??null,rowLabel:excluded?null:selected?.label.slice(0,300)??null,contributorIndex:excluded?null:projection.selection?.contributor_index??null,contributorCount:excluded?1:projection.selection?.contributor_count??0,excludedIndex:state.excludedIndex,evidenceBasis:contributor?.basis??(contributor?"ORIGINAL_SOURCE":null),reference};
 }catch{return {...scope,status:"unavailable"};}
}
export function activeSourceReviewContext(value:SourceReviewContext|null,target:Scope|null):SourceReviewContext|null {
 if(!target)return null;
 return value?.companyId===target.companyId&&value.invocationId===target.invocationId?value:{...target,status:"updating"};
}
export function sourceReviewForSession(value:{sessionKey:string;context:SourceReviewContext}|null,sessionKey:string,target:Scope|null):SourceReviewContext|null {
 return activeSourceReviewContext(value?.sessionKey===sessionKey?value.context:null,target);
}
export function explainSourceReview(value:SourceReviewContext):string {
 if(value.status!=="ready")return value.status==="updating"?"The exact source-review selection is updating. Its previous result is not current context for this answer.":"The exact source-review selection is unavailable or could not be verified. No previous result is used for this answer.";
 const selected=value.excludedIndex!==null?`Excluded evidence ${value.excludedIndex+1} is selected; it is outside the included result.`:value.rowKey?`Selected row: ${value.rowLabel}. Contributor ${value.contributorIndex===null?"unavailable":value.contributorIndex+1} of ${value.contributorCount}.`:"No result row is selected.";
 const basis=value.evidenceBasis==="CANONICAL_DEFINITION"?"Evidence establishes retained canonical attributes; original source cells are not established.":value.evidenceBasis==="UNAVAILABLE"?"Original source evidence is unavailable; a retained definition may be traced.":value.evidenceBasis==="ORIGINAL_SOURCE"?"Original retained source evidence is available for inspection.":"No contributor evidence is selected.";
 return `${value.title}. Recorded authority: ${value.authority.replaceAll("_"," ").toLowerCase()}. Coverage: ${value.returnedRows} of ${value.totalRows} retained rows returned by the exact query; this is not complete company coverage. ${selected} ${basis} Effective ${value.validAt}; known ${value.knownAt}. ${value.reference?"Trace and History open the exact retained version at that knowledge cutoff.":"No exact resource reference is available for Trace or History."} These references do not establish a financial cause, performance conclusion or permission for business action.`;
}
