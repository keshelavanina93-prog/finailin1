import type {CanonicalResource,CompanyRegulationPage,OperatorInspection} from "@finai/contracts";
import {companyCutoffs,type CompanyCutoffs} from "./company-360-descriptor";
import {assertCompanyRegulation} from "./company-regulation-state";
import {restorationInstant} from "./definition-restoration-time";

type CompanyPin=Pick<CanonicalResource,"resource_id"|"version_id"|"content_hash">;
export type CompanyRegulationHandoff=CompanyCutoffs&{company:CompanyPin};
export type CompanyRegulationEntry={token:string;entryId:string;handoff:CompanyRegulationHandoff};
const uuid=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i,hash=/^[a-f0-9]{64}$/;
export function validateRegulationHandoff(value:CompanyRegulationHandoff,companyId:string):CompanyRegulationHandoff {
 const cutoffs=companyCutoffs(value),company=value?.company;
 if(!cutoffs||company?.resource_id!==companyId||!uuid.test(company.resource_id)||!uuid.test(company.version_id)||!hash.test(company.content_hash))throw Error("Regulation could not preserve the selected company snapshot.");
 return {...cutoffs,company:{resource_id:company.resource_id,version_id:company.version_id,content_hash:company.content_hash}};
}
export function companyRegulationHandoff(company:CanonicalResource,validAt:string,knownAt:string):CompanyRegulationHandoff {
 if(company?.object_type!=="LegalEntity"||company.authority_state!=="APPROVED"||company.evidence_class==="REFERENCE_TEMPLATE")throw Error("The displayed company snapshot is unavailable for regulatory review.");
 return validateRegulationHandoff({company,validAt,knownAt},company.resource_id);
}
export function regulationEntryForSession(entry:CompanyRegulationEntry|null,token:string,companyId:string):CompanyRegulationEntry|null {
 return entry?.token===token&&entry.handoff.company.resource_id===companyId?entry:null;
}
export function regulationSnapshotKey(value?:CompanyRegulationHandoff):string {
 return value?JSON.stringify([value.company.resource_id,value.company.version_id,value.company.content_hash,restorationInstant(value.validAt),restorationInstant(value.knownAt)]):"current";
}
export function regulationRuleQuery(companyId:string,offset:number,handoff?:CompanyRegulationHandoff):string {
 if(!uuid.test(companyId)||!Number.isInteger(offset)||offset<0||offset>100000||offset%100)throw Error("The regulatory page reference is invalid.");
 const snapshot=handoff?validateRegulationHandoff(handoff,companyId):null;
 return new URLSearchParams({legal_entity_id:companyId,offset:String(offset),...(snapshot?{at:snapshot.validAt,known_at:snapshot.knownAt}:{})}).toString();
}
/** Rules resolve valid time; exact operator inspection independently verifies the company content pin. */
export function assertRegulationHandoffPage(page:CompanyRegulationPage,inspection:OperatorInspection,handoff:CompanyRegulationHandoff,offset:number):void {
 const expected=validateRegulationHandoff(handoff,handoff.company.resource_id),company=inspection?.resource;
 if(!company||company.resource_id!==expected.company.resource_id||company.version_id!==expected.company.version_id||company.content_hash!==expected.company.content_hash||company.object_type!=="LegalEntity"||company.authority_state!=="APPROVED"||company.evidence_class==="REFERENCE_TEMPLATE"||restorationInstant(inspection.known_at)!==restorationInstant(expected.knownAt))throw Error("Regulatory review did not retain the Company 360 resource version and content.");
 assertCompanyRegulation(page,{company,validAt:expected.validAt,knownAt:expected.knownAt,offset});
}
