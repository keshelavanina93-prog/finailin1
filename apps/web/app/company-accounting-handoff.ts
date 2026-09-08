import type {CanonicalResource,CompanyHomeDescriptor} from "@finai/contracts";
import {companyCutoffs,companySnapshot,type CompanyCutoffs} from "./company-360-descriptor";

import {restorationInstant} from "./definition-restoration-time";
import type {CompanyNyxContext,CompanyNyxReadback} from "./company-nyx-context";
import {journalReviewOriginMatches,type CompanyOriginReference} from "./journal-review-handoff";

type CompanyPin=Pick<CanonicalResource,"resource_id"|"version_id"|"content_hash">;
export type CompanyAccountingHandoff=CompanyCutoffs&{company:CompanyPin;tab:"accounting"};
export type CompanyAccountingEntry={token:string;entryId:string;handoff:CompanyAccountingHandoff;viewStateKey?:string};
const uuid=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i,hash=/^[a-f0-9]{64}$/;

/** An explicit drill carries references only, never a copied financial result. */
export function companyAccountingHandoff(home:CompanyHomeDescriptor):CompanyAccountingHandoff {
 const company=home.company;
 if(home.contract!=="g8-company-home/1"||home.current_use_authorized!==false||home.business_effect_authorized!==false||company?.object_type!=="LegalEntity"||company.authority_state!=="APPROVED"||company.evidence_class==="REFERENCE_TEMPLATE")throw Error("The Home accounting snapshot is unavailable.");
 return validateAccountingHandoff({company,validAt:home.valid_at,knownAt:home.known_at,tab:"accounting"},company.resource_id);
}
export function validateAccountingHandoff(value:CompanyAccountingHandoff,companyId:string):CompanyAccountingHandoff {
 const cutoffs=companyCutoffs(value),company=value?.company;
 if(!cutoffs||value.tab!=="accounting"||company?.resource_id!==companyId||!uuid.test(company.resource_id)||!uuid.test(company.version_id)||!hash.test(company.content_hash))throw Error("The accounting drill does not match this company and exact snapshot.");
 return {...cutoffs,tab:"accounting",company:{resource_id:company.resource_id,version_id:company.version_id,content_hash:company.content_hash}};
}
export function accountingEntryForSession(value:CompanyAccountingEntry|null,token:string,companyId:string):CompanyAccountingEntry|null {
 return value?.token===token&&value.handoff.company.resource_id===companyId?value:null;
}
/** Company360 still resolves authority on the server before accepting the handoff. */
export function accountingCompanySnapshot(value:unknown,companyId:string,requested:CompanyCutoffs|null,handoff:CompanyAccountingHandoff|null) {
 const snapshot=companySnapshot(value,companyId,requested);
 if(handoff){
  const expected=validateAccountingHandoff(handoff,companyId);
  companySnapshot(value,companyId,expected);
  if(snapshot.context.company.version_id!==expected.company.version_id||snapshot.context.company.content_hash!==expected.company.content_hash)throw Error("The company revision differs from the Home accounting snapshot. Reopen Home or explicitly choose another snapshot.");
 }
 return snapshot;
}

export type CompanyAccountingOrigin=CompanyOriginReference&{kind:"accounting";handoff:CompanyAccountingHandoff};
export const isCompanyAccountingOrigin=(value:CompanyOriginReference&{kind?:string}):value is CompanyAccountingOrigin=>value.kind==="accounting";
/** The Home return snapshot is independent of explicit accounting choices made in the foreground. */
export function companyAccountingOrigin(context:CompanyNyxContext|null,value:CompanyAccountingHandoff):CompanyAccountingOrigin {
 if(context?.status!=="ready"||context.company.resource_id!==context.companyId)throw Error("The original Home snapshot is unavailable. No latest accounting context has been substituted.");
 const handoff=validateAccountingHandoff(value,context.companyId),company={...handoff.company,display_name:context.company.display_name};
 const reference={kind:"accounting" as const,company,validAt:handoff.validAt,knownAt:handoff.knownAt,handoff};
 if(!journalReviewOriginMatches(reference,context))throw Error("The accounting drill does not match the displayed Home company version and time.");
 return reference;
}
export function accountingOriginViewKey(contextKey:string,reference:CompanyAccountingOrigin):string {
 const handoff=validateAccountingHandoff(reference.handoff,reference.company.resource_id);
 if(reference.kind!=="accounting"||reference.company.version_id!==handoff.company.version_id||reference.company.content_hash!==handoff.company.content_hash||restorationInstant(reference.validAt)!==restorationInstant(handoff.validAt)||restorationInstant(reference.knownAt)!==restorationInstant(handoff.knownAt))throw Error("The accounting origin snapshot is inconsistent.");
 return `${contextKey}:companies:${reference.company.resource_id}:home:${JSON.stringify([handoff.company.version_id,handoff.company.content_hash,restorationInstant(handoff.validAt),restorationInstant(handoff.knownAt)])}`;
}
/** Only the foreground's current readback may describe its selected accounting snapshot to NYX. */
export function accountingForegroundContext(value:CompanyNyxReadback|null,key:string|null,companyId:string):CompanyNyxContext|null {
 if(!key)return null;
 return value?.key===key&&value.context.companyId===companyId?value.context:{companyId,status:"updating"};
}

/** Retain only an accepted foreground readback; Home's immutable return reference is not changed. */
export function accountingContinuation(context:CompanyNyxContext,companyId:string):CompanyAccountingHandoff|null {
 if(context.status!=="ready")return null;
 if(context.companyId!==companyId)throw Error("The accounting readback belongs to another company.");
 return validateAccountingHandoff({company:context.company,validAt:context.validAt,knownAt:context.knownAt,tab:"accounting"},companyId);
}
