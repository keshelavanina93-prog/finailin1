import {assertCompanyJournalReviews} from "./company-journal-review-state";

export type JournalAnalysisSource={invocationId:string;title:string;acceptedReviews:number};
export type JournalAnalysisEntries={companyId:string;observedAt:string;state:"AVAILABLE"|"UNAVAILABLE";reason:string|null;truncated:boolean;sources:JournalAnalysisSource[]};

/** Current reviewed source references only; never journal amounts or a historical financial claim. */
export function companyJournalAnalysisEntries(value:unknown,companyId:string):JournalAnalysisEntries {
 if(!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(companyId))throw Error("Choose an exact company before opening accepted journal sources.");
 assertCompanyJournalReviews(value,companyId);
 const proposals=new Set<string>(),requests=new Map<string,string>(),sources=new Map<string,JournalAnalysisSource>();
 for(const item of value.items){
  if(proposals.has(item.proposal_id)||requests.has(item.request_id)&&requests.get(item.request_id)!==item.invocation_id)throw Error("Journal source references conflict with their retained request or proposal.");
  proposals.add(item.proposal_id);requests.set(item.request_id,item.invocation_id);
  if(item.state!=="PUBLISHED")continue;
  const source=sources.get(item.invocation_id);
  if(source)source.acceptedReviews++;
  else sources.set(item.invocation_id,{invocationId:item.invocation_id,title:item.title,acceptedReviews:1});
 }
 return {companyId,observedAt:value.observed_at,state:value.state,reason:value.reason,truncated:value.truncated,sources:[...sources.values()]};
}

/** A chooser from an earlier observation cannot open a result after the collection changes. */
export function journalAnalysisEntryTarget(entries:JournalAnalysisEntries,invocationId:string,observedAt:string):{companyId:string;invocationId:string} {
 if(entries.state!=="AVAILABLE"||entries.observedAt!==observedAt||!entries.sources.some(source=>source.invocationId===invocationId))throw Error("This accepted journal source is no longer in the displayed review collection. Select a returned source again.");
 return {companyId:entries.companyId,invocationId};
}
