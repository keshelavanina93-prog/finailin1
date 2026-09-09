import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import ts from "typescript";
const helper=readFileSync(new URL("../app/definition-restoration-time.ts",import.meta.url),"utf8");
const source=readFileSync(new URL("../app/company-changes-state.ts",import.meta.url),"utf8").replace('import {restorationInstant} from "./definition-restoration-time";',helper);
const {assertCompanyChanges,priorKnowledge}=await import(`data:text/javascript;base64,${Buffer.from(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText).toString("base64")}`);
const company={resource_id:"11111111-1111-4111-8111-111111111111",version_id:"22222222-2222-4222-8222-222222222222",content_hash:"a".repeat(64),object_type:"LegalEntity",display_name:"Company",authority_state:"APPROVED",evidence_class:"AUTHENTIC_SOURCE"};
const before={...company,resource_id:"33333333-3333-4333-8333-333333333333",object_type:"Contract",display_name:"Before"};
const after={...before,version_id:"44444444-4444-4444-8444-444444444444",content_hash:"b".repeat(64),display_name:"After"};
const request={company_id:company.resource_id,valid_at:"2026-09-08T01:00:00.123456Z",known_at:"2026-09-08T01:00:00.123456Z",compare_known_at:"2026-09-07T01:00:00.123456Z"};
const change={resource_id:before.resource_id,kind:"CHANGED_VERSION",before,after,changed_fields:["/display_name"]};
const fixture=()=>({contract:"g8-company-changes/1",company,...request,authority:"RETAINED_COMPANY_CONTEXT_COMPARISON",coverage:"EXPLICIT_COMPANY_CONTEXT",changes:[change],limitations:["Recorded context only."],current_use_authorized:false,business_effect_authorized:false});
test("comparison retains company and independent exact knowledge cutoffs",()=>{
 assert.doesNotThrow(()=>assertCompanyChanges(fixture(),request));
 assert.doesNotThrow(()=>assertCompanyChanges({...fixture(),known_at:"2026-09-08T05:00:00.123456+04:00"},request));
 for(const update of [{known_at:"2026-09-08T01:00:00.123457Z"},{compare_known_at:request.known_at},{valid_at:request.compare_known_at},{company:before},{company:{...company,authority_state:"PENDING"}},{authority:"FINANCIAL_MATERIALITY"},{coverage:"WHOLE_COMPANY"},{business_effect_authorized:true}])assert.throws(()=>assertCompanyChanges({...fixture(),...update},request));
});
test("membership changes are distinct from changed versions and fail inconsistent identities",()=>{
 for(const row of [{...change,kind:"ADDED_TO_CONTEXT",before:null,changed_fields:[]},{...change,kind:"REMOVED_FROM_CONTEXT",after:null,changed_fields:[]}])assert.doesNotThrow(()=>assertCompanyChanges({...fixture(),changes:[row]},request));
 for(const row of [{...change,after:before},{...change,before:null},{...change,kind:"DELETED"},{...change,after:{...after,resource_id:company.resource_id}},{...change,after:{...after,object_type:"LegalEntity"}},{...change,after:{...after,evidence_class:"REFERENCE_TEMPLATE"}},{...change,kind:"ADDED_TO_CONTEXT"},{...change,changed_fields:["unbounded field"]}])assert.throws(()=>assertCompanyChanges({...fixture(),changes:[row]},request));
 assert.throws(()=>assertCompanyChanges({...fixture(),changes:[change,change]},request));
 assert.throws(()=>assertCompanyChanges({...fixture(),limitations:[]},request));
});
test("knowledge presets preserve microseconds and normalize timezone without shifting effective time",()=>{
 assert.equal(priorKnowledge("2026-09-08T05:00:00.123456+04:00",1),request.compare_known_at);
 assert.equal(priorKnowledge(request.known_at,7),"2026-09-01T01:00:00.123456Z");
 assert.throws(()=>priorKnowledge(request.known_at,0));
 assert.throws(()=>priorKnowledge("2026-09-08T01:00:00",1));
 assert.throws(()=>assertCompanyChanges(fixture(),{...request,compare_known_at:request.known_at}));
 assert.throws(()=>assertCompanyChanges(fixture(),{...request,compare_known_at:"2026-09-09T01:00:00.123456Z"}));
});
