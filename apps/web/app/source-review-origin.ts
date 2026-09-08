/** Navigation references only. Never retain business values or trust a destination URL. */
export const sourceReviewViews=["home","companies","finance","data","ontology","system","operations","regulation","actions"] as const;
export type SourceReviewOrigin={version:1;sessionId:string;entryId:string;companyId:string;invocationId:string;view:typeof sourceReviewViews[number];scroll:number};
const uuid=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i;
export function parseSourceReviewOrigin(value:unknown,sessionId:string,target?:{companyId:string;invocationId:string}):SourceReviewOrigin|null {
 if(!value||typeof value!=="object"||Array.isArray(value))return null;
 const item=value as Partial<SourceReviewOrigin>;
 if(item.version!==1||item.sessionId!==sessionId||!uuid.test(sessionId)||typeof item.entryId!=="string"||!uuid.test(item.entryId)||typeof item.companyId!=="string"||!uuid.test(item.companyId)||typeof item.invocationId!=="string"||!uuid.test(item.invocationId)||!sourceReviewViews.includes(item.view!)||typeof item.scroll!=="number"||!Number.isFinite(item.scroll)||item.scroll<0||item.scroll>10000000||target&&(item.companyId!==target.companyId||item.invocationId!==target.invocationId))return null;
 return {version:1,sessionId,entryId:item.entryId,companyId:item.companyId,invocationId:item.invocationId,view:item.view!,scroll:item.scroll};
}
