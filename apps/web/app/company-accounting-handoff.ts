import type {CanonicalResource,CompanyHomeDescriptor} from "@finai/contracts";
import {companyCutoffs,companySnapshot,type CompanyCutoffs} from "./company-360-descriptor";

type CompanyPin=Pick<CanonicalResource,"resource_id"|"version_id"|"content_hash">;
export type CompanyAccountingHandoff=CompanyCutoffs&{company:CompanyPin;tab:"accounting"};
export type CompanyAccountingEntry={token:string;entryId:string;handoff:CompanyAccountingHandoff};
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
