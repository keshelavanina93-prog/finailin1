import type {CanonicalResource,CompanyJournalReviewItem,CompanyConditionWorkItem} from "@finai/contracts";
import {companyCutoffs} from "./company-360-descriptor";
import type {CompanyNyxContext} from "./company-nyx-context";
import {restorationInstant} from "./definition-restoration-time";

export type JournalReviewReference={company:Pick<CanonicalResource,"resource_id"|"version_id"|"content_hash"|"display_name">;validAt:string;knownAt:string;proposalId:string;requestId:string;invocationId:string};
export type JournalReviewEntry={entryId:string;token:string;returnView:"home"|"companies";reference:JournalReviewReference};
export type CompanyWorkflowReference=Pick<JournalReviewReference,"company"|"validAt"|"knownAt">&{kind:"workflow";workflowId:string;proposalId:string;observedAt:string};
export type CompanyWorkReference=JournalReviewReference|CompanyWorkflowReference;
export type CompanyWorkEntry=Omit<JournalReviewEntry,"reference">&{reference:CompanyWorkReference};
const operationId=/^opa_[a-f0-9]{64}$/;
const uuid=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i,hash=/^[a-f0-9]{64}$/;
export function journalReviewReference(company:CanonicalResource,validAt:string,knownAt:string,item:CompanyJournalReviewItem):JournalReviewReference {
 if(company?.object_type!=="LegalEntity"||company.authority_state!=="APPROVED"||company.evidence_class==="REFERENCE_TEMPLATE"||!companyCutoffs({validAt,knownAt})||!uuid.test(company.resource_id)||!uuid.test(company.version_id)||!hash.test(company.content_hash)||typeof company.display_name!=="string"||item.company_id!==company.resource_id||item.basis!=="EXPLICIT_JOURNAL_PRODUCTION_REQUEST"||!["PENDING_REVIEW","PUBLISHED","REJECTED"].includes(item.state)||![item.proposal_id,item.request_id,item.invocation_id].every(value=>uuid.test(value)))throw Error("The journal review does not retain this company snapshot and submitted proposal.");
 return {company:{resource_id:company.resource_id,version_id:company.version_id,content_hash:company.content_hash,display_name:company.display_name},validAt,knownAt,proposalId:item.proposal_id,requestId:item.request_id,invocationId:item.invocation_id};
}
export function journalReviewEntryForSession<T extends CompanyWorkEntry>(value:T|null,token:string,companyId:string,view:string):T|null {
 return value?.token===token&&value.reference.company.resource_id===companyId&&value.returnView===view&&uuid.test(value.entryId)?value:null;
}
/** The origin is navigation context only; current proposal decisions retain their own observation time. */
export function journalReviewOriginMatches(reference:Pick<JournalReviewReference,"company"|"validAt"|"knownAt">,context:CompanyNyxContext|null):boolean {
 return context?.status==="ready"&&context.companyId===reference.company.resource_id&&context.company.version_id===reference.company.version_id&&context.company.content_hash===reference.company.content_hash&&restorationInstant(context.validAt)===restorationInstant(reference.validAt)&&restorationInstant(context.knownAt)===restorationInstant(reference.knownAt);
}
export function journalReviewHistoryMode(state:unknown,entry:CompanyWorkEntry|null):"review"|"return"|"refused"|null {
 if(!state||typeof state!=="object")return null;
 const value=state as Record<string,unknown>;
 const review=value.g8JournalReview,back=value.g8JournalReturn;
 if(review===undefined&&back===undefined)return null;
 if(review!==undefined&&back!==undefined)return "refused";
 if(review!==undefined)return typeof review==="string"&&review===entry?.entryId?"review":"refused";
 return typeof back==="string"&&back===entry?.entryId?"return":"refused";
}
export type JournalReviewDomOrigin={element:HTMLElement;queue:HTMLElement;scroll:number;scrolls:Array<{element:HTMLElement;top:number;left:number}>};
/** The origin wrapper uses display:contents and intentionally has no layout box. */
export function restoreJournalReviewFocus(origin:JournalReviewDomOrigin,main:HTMLElement|null,proposalId:string):boolean {
 return restoreCompanyWorkFocus(origin,main,{proposalId});
}
export function restoreCompanyWorkFocus(origin:JournalReviewDomOrigin,main:HTMLElement|null,reference:{proposalId:string;workflowId?:string}):boolean {
 const workflow=reference.workflowId,id=workflow??reference.proposalId;
 if(!(workflow?operationId:uuid).test(id)||!origin.element.isConnected||!origin.queue.isConnected||origin.element.hidden||origin.element.inert)return false;
 main?.scrollTo({top:origin.scroll,behavior:"instant"});
 for(const item of origin.scrolls)if(item.element.isConnected)item.element.scrollTo({top:item.top,left:item.left,behavior:"instant"});
 const row=origin.queue.querySelector<HTMLElement>(`[${workflow?"data-company-workflow":"data-journal-proposal"}="${id}"]`);
 (row?.getClientRects().length?row:origin.queue).focus({preventScroll:true});
 return true;
}

/** Current work observation is independent from the pinned company resource snapshot. */
export function companyWorkflowReference(company:CanonicalResource,validAt:string,knownAt:string,observedAt:string,item:CompanyConditionWorkItem):CompanyWorkflowReference {
 if(company?.object_type!=="LegalEntity"||company.authority_state!=="APPROVED"||company.evidence_class==="REFERENCE_TEMPLATE"||!companyCutoffs({validAt,knownAt})||!restorationInstant(observedAt)||!uuid.test(company.resource_id)||!uuid.test(company.version_id)||!hash.test(company.content_hash)||typeof company.display_name!=="string"||item.company_id!==company.resource_id||item.basis!=="EXPLICIT_INVOCATION"||!["PREPARED","PENDING_REVIEW","PUBLISHED","REJECTED"].includes(item.state)||!operationId.test(item.workflow_id)||!item.proposal_id||!uuid.test(item.proposal_id))throw Error("The workflow does not retain this company snapshot and canonical operation reference.");
 return {kind:"workflow",company:{resource_id:company.resource_id,version_id:company.version_id,content_hash:company.content_hash,display_name:company.display_name},validAt,knownAt,workflowId:item.workflow_id,proposalId:item.proposal_id,observedAt};
}
