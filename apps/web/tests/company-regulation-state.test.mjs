import test from "node:test";
import assert from "node:assert/strict";
import {loadTypeScript} from "./load-typescript.mjs";
const {assertCompanyRegulation}=await loadTypeScript(new URL("../app/company-regulation-state.ts",import.meta.url));
function fixture(){const company={resource_id:"company",version_id:"historical-company"};const expected={company,validAt:"2025-01-01T00:00:00.123456Z",knownAt:"2025-02-01T00:00:00.654321Z",offset:0};return {expected,data:{company,at:expected.validAt,known_at:expected.knownAt,context_basis:"INCOMPLETE_CONTEXT",activity:null,accounting_effects_created:false,next_offset:null,rules:[{resource:{resource_id:"rule",version_id:"retained-rule",content_hash:"a".repeat(64),display_name:"Retained interpretation",object_type:"RegulatoryRule",authority_state:"APPROVED",evidence_class:"SOURCE_BOUND",attributes:{legal_entity_id:"company",definition:{provision:"Reviewed provision",effective_from:"2026-01-01"}}},dependencies:{},assessment:{legal_state:"FUTURE_EFFECTIVE",applicability:"CONTEXT_REQUIRED",effective_obligation:false,obligation:"Retained wording",days_to_deadline:null,blocking_reasons:["FUTURE_EFFECTIVE","CONTEXT_REQUIRED"]}}]}};}
test("retained future interpretations preserve exact company/time without asserting applicability",()=>{
 const {data,expected}=fixture();assert.doesNotThrow(()=>assertCompanyRegulation(data,expected));
 data.rules[0].assessment.legal_state="CURRENT_EFFECTIVE";data.rules[0].assessment.applicability="LICENCE_BINDING_REQUIRED";assert.doesNotThrow(()=>assertCompanyRegulation(data,expected));
 data.rules=[];data.next_offset=100;assert.doesNotThrow(()=>assertCompanyRegulation(data,expected));
});
test("company, version, microsecond cutoffs and registry pagination cannot silently change",()=>{
 for(const patch of [{company:{resource_id:"other",version_id:"historical-company"}},{company:{resource_id:"company",version_id:"current-company"}},{at:"2025-01-01T00:00:00.123457Z"},{known_at:"2025-02-01T00:00:00.654322Z"},{next_offset:200}]){const {data,expected}=fixture();assert.throws(()=>assertCompanyRegulation({...data,...patch},expected));}
});
test("inferred context, asserted obligations and unaccepted or foreign rules fail closed",()=>{
 for(const patch of [{context_basis:"USER_SUPPLIED_SCENARIO"},{activity:"DISTRIBUTION"},{accounting_effects_created:true}]){const {data,expected}=fixture();assert.throws(()=>assertCompanyRegulation({...data,...patch},expected));}
 for(const patch of [{effective_obligation:true},{applicability:"APPLICABLE"},{legal_state:"CERTIFIED"},{days_to_deadline:1.5}]){const {data,expected}=fixture();Object.assign(data.rules[0].assessment,patch);assert.throws(()=>assertCompanyRegulation(data,expected));}
 for(const patch of [{authority_state:"PROPOSED"},{evidence_class:"REFERENCE_TEMPLATE"},{object_type:"Licence"},{attributes:{legal_entity_id:"other"}}]){const {data,expected}=fixture();Object.assign(data.rules[0].resource,patch);assert.throws(()=>assertCompanyRegulation(data,expected));}
});
