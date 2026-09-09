import type {Result} from "./regulation-workspace";
import {restorationInstant} from "./definition-restoration-time";

export type RegulatoryScenario={legal_entity_id:string;activity:string;customer_count:number|null;at:string;known_at:string|null};
type Expected={companyId:string;runId?:string;scenario?:RegulatoryScenario};
const uuid=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i,run=/^fcr_[a-f0-9]{64}$/;
const object=(value:unknown):value is Record<string,unknown>=>Boolean(value)&&typeof value==="object"&&!Array.isArray(value);
const text=(value:unknown)=>typeof value==="string";
const instant=(left:unknown,right:unknown)=>typeof left==="string"&&typeof right==="string"&&Boolean(restorationInstant(left))&&restorationInstant(left)===restorationInstant(right);

/** Retained scenarios keep their own company version and dates, separate from the company page. */
export function assertRetainedRegulatoryAssessment(value:unknown,expected:Expected):asserts value is Result&{run_id:string} {
 const fail=()=>{throw Error("The retained assessment does not match the selected company and exact scenario reference. No result has been substituted.");};
 if(!object(value)||!uuid.test(expected.companyId))return fail();
 const company=value.company,context=value.assessment_context;
 if(value.contract!=="regulatory-assessment/1"||value.coverage!=="COMPLETE_AUTHORIZED_RULE_SCAN"||value.context_basis!=="USER_SUPPLIED_SCENARIO"||value.accounting_effects_created!==false||typeof value.run_id!=="string"||!run.test(value.run_id)||expected.runId!==undefined&&value.run_id!==expected.runId||value.next_offset!==null||!object(company)||!object(context))return fail();
 if(company.resource_id!==expected.companyId||context.legal_entity_id!==expected.companyId||typeof company.version_id!=="string"||!uuid.test(company.version_id)||!text(company.display_name)||!instant(value.at,context.at)||!instant(value.known_at,context.known_at)||!text(context.activity)||value.activity!==context.activity||context.customer_count!==null&&(!Number.isSafeInteger(context.customer_count)||(context.customer_count as number)<0))return fail();
 const scenario=expected.scenario;
 if(scenario&&(scenario.legal_entity_id!==expected.companyId||context.activity!==scenario.activity||context.customer_count!==scenario.customer_count||!instant(context.at,scenario.at)||scenario.known_at!==null&&!instant(context.known_at,scenario.known_at)))return fail();
 if(!Array.isArray(value.rules)||value.rules.length>10000||value.no_rules_found!==(value.rules.length===0))return fail();
 for(const item of value.rules){
  if(!object(item)||!object(item.resource)||!object(item.assessment))return fail();
  const resource=item.resource,assessment=item.assessment;
  if(typeof resource.resource_id!=="string"||!uuid.test(resource.resource_id)||typeof resource.version_id!=="string"||!uuid.test(resource.version_id)||!text(resource.display_name)||!object(resource.attributes))return fail();
  const attributes=resource.attributes,definition=attributes.definition;
  if(attributes.legal_entity_id!==expected.companyId||!object(definition)||![definition.provision,definition.source_version,definition.effective_from,attributes.act_id,attributes.evidence_id,attributes.licence_id].every(text)||definition.deadline!==null&&!text(definition.deadline)||![assessment.legal_state,assessment.applicability,assessment.obligation].every(text)||typeof assessment.effective_obligation!=="boolean"||assessment.days_to_deadline!==null&&!Number.isSafeInteger(assessment.days_to_deadline)||assessment.blocking_reasons!==undefined&&(!Array.isArray(assessment.blocking_reasons)||!assessment.blocking_reasons.every(text)))return fail();
 }
}
