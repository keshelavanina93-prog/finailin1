import {journalSnapshot as exactJournalSnapshot} from "./analysis-projection-identity";
/** Navigation references only. Never retain business values or trust a destination URL. */
export const sourceReviewViews=["home","companies","finance","data","ontology","system","operations","regulation","actions"] as const;
export type SourceReviewOrigin={version:1;sessionId:string;entryId:string;companyId:string;invocationId:string;journalSnapshot?:string;view:typeof sourceReviewViews[number];scroll:number};
const uuid=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i;
export function parseSourceReviewOrigin(value:unknown,sessionId:string,target?:{companyId:string;invocationId:string;journalSnapshot?:string}):SourceReviewOrigin|null {
 if(!value||typeof value!=="object"||Array.isArray(value))return null;
 const item=value as Partial<SourceReviewOrigin>;
 let snapshot:string|undefined,targetSnapshot:string|undefined;try{targetSnapshot=target?.journalSnapshot===undefined?undefined:exactJournalSnapshot(target.journalSnapshot);snapshot="journalSnapshot" in item?exactJournalSnapshot(item.journalSnapshot):undefined;}catch{return null;}
 if(item.version!==1||item.sessionId!==sessionId||!uuid.test(sessionId)||typeof item.entryId!=="string"||!uuid.test(item.entryId)||typeof item.companyId!=="string"||!uuid.test(item.companyId)||typeof item.invocationId!=="string"||!uuid.test(item.invocationId)||!sourceReviewViews.includes(item.view!)||typeof item.scroll!=="number"||!Number.isFinite(item.scroll)||item.scroll<0||item.scroll>10000000||target&&(item.companyId!==target.companyId||item.invocationId!==target.invocationId||snapshot!==targetSnapshot))return null;
 return {version:1,sessionId,entryId:item.entryId,companyId:item.companyId,invocationId:item.invocationId,...(snapshot===undefined?{}:{journalSnapshot:snapshot}),view:item.view!,scroll:item.scroll};
}
