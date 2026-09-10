import type {CanonicalResource} from "@finai/contracts";
import {companyCutoffs} from "./company-360-descriptor";

export type ReadyCompanyNyxContext={status:"ready";companyId:string;company:Pick<CanonicalResource,"resource_id"|"version_id"|"content_hash"|"display_name">;validAt:string;knownAt:string};
export type CompanyNyxContext=ReadyCompanyNyxContext|{status:"updating"|"unavailable";companyId:string};
export type CompanyNyxReadback={key:string;context:CompanyNyxContext};
const uuid=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i,hash=/^[a-f0-9]{64}$/;
/** References from the validated displayed response; never shell defaults or financial state. */
export function companyNyxContext(companyId:string,company:CanonicalResource|null,validAt:string,knownAt:string,state:"ready"|"updating"|"unavailable"):CompanyNyxContext {
 if(state!=="ready")return {companyId,status:state};
 if(!company||company.resource_id!==companyId||company.object_type!=="LegalEntity"||company.authority_state!=="APPROVED"||company.evidence_class==="REFERENCE_TEMPLATE"||!uuid.test(companyId)||!uuid.test(company.version_id)||!hash.test(company.content_hash)||typeof company.display_name!=="string"||!companyCutoffs({validAt,knownAt}))return {companyId,status:"unavailable"};
 return {companyId,status:"ready",company:{resource_id:companyId,version_id:company.version_id,content_hash:company.content_hash,display_name:company.display_name},validAt,knownAt};
}
export function companyNyxForSurface(value:CompanyNyxReadback|null,key:string,companyId:string,active:boolean):CompanyNyxContext|null {
 if(!active||!companyId)return null;
 return value?.key===key&&value.context.companyId===companyId?value.context:{companyId,status:"updating"};
}
export function companyNyxFallback(value:CompanyNyxContext|null|undefined,selected:{source:boolean;trace:boolean;resource:boolean;map:boolean;work:boolean;pending?:boolean;refused?:boolean}):CompanyNyxContext|null {
 return Object.values(selected).some(Boolean)?null:value??null;
}
export function companyNyxCaption(value:CompanyNyxContext):string {
 return value.status==="ready"?`${value.company.display_name} · company canvas effective ${value.validAt} · known ${value.knownAt}`:value.status==="updating"?"Company canvas snapshot updating":"Company canvas snapshot unavailable";
}
export function explainCompanyNyx(value:CompanyNyxContext):string {
 if(value.status!=="ready")return "The displayed company snapshot is "+(value.status==="updating"?"updating":"unavailable")+". No earlier company version or shell accounting context is used for this answer.";
 return `${companyNyxCaption(value)}. This is the accepted company definition shown in the canvas. Trace and History retain its exact version and knowledge cutoff. These references do not establish financial performance, accounting eligibility or business-action authority. Fiscal periods, retained analyses and current work queues keep their independently stated times.`;
}
