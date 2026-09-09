import type {CanonicalResource,CompanyRegulationPage} from "@finai/contracts";
export type {CompanyRegulationPage} from "@finai/contracts";
import {restorationInstant} from "./definition-restoration-time";

export const regulatoryStateLabels:Record<string,string>={CURRENT_EFFECTIVE:"Within stated effective dates",FUTURE_EFFECTIVE:"Future effective date",EXPIRED:"Past stated effective dates",DRAFT:"Draft interpretation",POLICY_INTENT:"Policy intention",SOURCE_VERSION_INCOMPLETE:"Source version incomplete"};
export const regulatoryContextLabels:Record<string,string>={CONTEXT_REQUIRED:"Activity context required",LICENCE_BINDING_REQUIRED:"Exact licence binding required",LICENCE_SCAN_INCOMPLETE:"Licence coverage incomplete"};

export function assertCompanyRegulation(value:CompanyRegulationPage,expected:{company:CanonicalResource;validAt:string;knownAt:string;offset:number}):void {
 const sameTime=(a:string,b:string)=>Boolean(restorationInstant(a)&&restorationInstant(a)===restorationInstant(b));
 if(!value||value.company?.resource_id!==expected.company.resource_id||value.company.version_id!==expected.company.version_id||
  !sameTime(value.at,expected.validAt)||!sameTime(value.known_at,expected.knownAt)||value.context_basis!=="INCOMPLETE_CONTEXT"||value.activity!==null||value.accounting_effects_created!==false||
  value.next_offset!==null&&value.next_offset!==expected.offset+100)throw Error("Regulatory context did not preserve this company and exact snapshot.");
 if(!Array.isArray(value.rules)||value.rules.length>100||new Set(value.rules.map(row=>row.resource?.resource_id)).size!==value.rules.length)throw Error("Retained regulatory page is invalid.");
 for(const row of value.rules){const r=row.resource,a=row.assessment;
  if(!r||r.object_type!=="RegulatoryRule"||r.authority_state!=="APPROVED"||r.evidence_class==="REFERENCE_TEMPLATE"||r.attributes?.legal_entity_id!==expected.company.resource_id||!r.version_id||!r.content_hash||typeof r.display_name!=="string"||
   !a||!Object.hasOwn(regulatoryStateLabels,a.legal_state)||!Object.hasOwn(regulatoryContextLabels,a.applicability)||a.effective_obligation!==false||typeof a.obligation!=="string"||
   a.days_to_deadline!==null&&!Number.isSafeInteger(a.days_to_deadline)||!Array.isArray(a.blocking_reasons)||a.blocking_reasons.some(reason=>typeof reason!=="string"))throw Error("A regulatory interpretation lacks retained scope or asserts unsupported applicability.");
  if(!r.attributes.definition||typeof r.attributes.definition!=="object")throw Error("Retained regulatory definition is unavailable.");
 }
}
