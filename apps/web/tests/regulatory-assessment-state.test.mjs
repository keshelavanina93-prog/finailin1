import test from "node:test";
import assert from "node:assert/strict";
import {loadTypeScript} from "./load-typescript.mjs";
const {assertRetainedRegulatoryAssessment}=await loadTypeScript(new URL("../app/regulatory-assessment-state.ts",import.meta.url));
const id=n=>`00000000-0000-4000-8000-${String(n).padStart(12,"0")}`;
function fixture(){return {run_id:"fcr_"+"a".repeat(64),contract:"regulatory-assessment/1",coverage:"COMPLETE_AUTHORIZED_RULE_SCAN",context_basis:"USER_SUPPLIED_SCENARIO",accounting_effects_created:false,company:{resource_id:id(1),version_id:id(2),display_name:"Selected company"},activity:"DISTRIBUTION",at:"2025-01-01T00:00:00.123456Z",known_at:"2026-01-01T00:00:00.654321Z",assessment_context:{legal_entity_id:id(1),activity:"DISTRIBUTION",customer_count:null,at:"2025-01-01T00:00:00.123456Z",known_at:"2026-01-01T00:00:00.654321Z"},rules:[],next_offset:null,no_rules_found:true};}
test("retained scenario verifies original company version, exact run and its own time basis",()=>{
 const value=fixture(),before=structuredClone(value);assert.doesNotThrow(()=>assertRetainedRegulatoryAssessment(value,{companyId:id(1),runId:value.run_id}));assert.deepEqual(value,before);
 value.assessment_context.known_at="2026-01-01T04:00:00.654321+04:00";assert.doesNotThrow(()=>assertRetainedRegulatoryAssessment(value,{companyId:id(1)}));
 for(const patch of [{company:{...value.company,resource_id:id(9)}},{company:{...value.company,version_id:"latest"}},{assessment_context:{...value.assessment_context,legal_entity_id:id(9)}},{assessment_context:{...value.assessment_context,known_at:"2026-01-01T00:00:00.654322Z"}}])assert.throws(()=>assertRetainedRegulatoryAssessment({...value,...patch},{companyId:id(1)}));
 assert.throws(()=>assertRetainedRegulatoryAssessment(value,{companyId:id(1),runId:"fcr_"+"b".repeat(64)}));
});
test("explicit scenario creation must return the submitted activity, count and requested cutoffs",()=>{
 const value=fixture(),scenario={...value.assessment_context};assert.doesNotThrow(()=>assertRetainedRegulatoryAssessment(value,{companyId:id(1),scenario}));
 assert.doesNotThrow(()=>assertRetainedRegulatoryAssessment(value,{companyId:id(1),scenario:{...scenario,known_at:null}}));
 for(const patch of [{legal_entity_id:id(9)},{activity:"SUPPLY"},{customer_count:0},{at:"2025-01-01T00:00:00.123457Z"},{known_at:"2026-01-01T00:00:00.654322Z"}])assert.throws(()=>assertRetainedRegulatoryAssessment(value,{companyId:id(1),scenario:{...scenario,...patch}}));
});
test("incomplete, unretained or accounting-effect results cannot become a company scenario",()=>{
 for(const patch of [{contract:"draft"},{coverage:"PARTIAL"},{context_basis:"INCOMPLETE_CONTEXT"},{accounting_effects_created:true},{run_id:"draft"},{next_offset:100},{no_rules_found:false},{known_at:"2026-01-01T00:00:00"},{assessment_context:{...fixture().assessment_context,customer_count:-1}}])assert.throws(()=>assertRetainedRegulatoryAssessment({...fixture(),...patch},{companyId:id(1)}));
});
test("nonempty retained rules require exact resource references and readable assessment fields",()=>{
 const value=fixture();value.no_rules_found=false;value.rules=[{resource:{resource_id:id(3),version_id:id(4),display_name:"Retained interpretation",attributes:{legal_entity_id:id(1),act_id:id(5),evidence_id:id(6),licence_id:id(7),definition:{provision:"Article",source_version:"Historical publication",effective_from:"2025-01-01",deadline:null}}},assessment:{legal_state:"CURRENT_EFFECTIVE",applicability:"APPLICABLE",effective_obligation:true,obligation:"Retained obligation",days_to_deadline:null,blocking_reasons:[]}}];
 assert.doesNotThrow(()=>assertRetainedRegulatoryAssessment(value,{companyId:id(1)}));
 const broken=structuredClone(value);broken.rules[0].resource.version_id="current";assert.throws(()=>assertRetainedRegulatoryAssessment(broken,{companyId:id(1)}));
 const foreign=structuredClone(value);foreign.rules[0].resource.attributes.legal_entity_id=id(9);assert.throws(()=>assertRetainedRegulatoryAssessment(foreign,{companyId:id(1)}));
 const invalid=structuredClone(value);invalid.rules[0].assessment.blocking_reasons=[{}];assert.throws(()=>assertRetainedRegulatoryAssessment(invalid,{companyId:id(1)}));
});
