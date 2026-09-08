import assert from "node:assert/strict";
import test from "node:test";
import {loadTypeScript} from "./load-typescript.mjs";
const {companyNyxContext,companyNyxForSurface,companyNyxFallback,companyNyxCaption,explainCompanyNyx}=await loadTypeScript(new URL("../app/company-nyx-context.ts",import.meta.url));
const id="11111111-1111-4111-8111-111111111111",version="22222222-2222-4222-8222-222222222222",hash="a".repeat(64);
const valid="2026-09-08T04:01:58.934174+00:00",known="2026-09-08T08:02:00.433237+04:00";
const company={resource_id:id,version_id:version,content_hash:hash,display_name:"Retained company name",object_type:"LegalEntity",authority_state:"APPROVED",evidence_class:"SOURCE_BOUND",attributes:{profit:"must not copy",period:"must not infer"}};
const ready=()=>companyNyxContext(id,company,valid,known,"ready");
test("company context carries exact displayed definition and cutoffs without financial attributes",()=>{
 const value=ready();
 assert.deepEqual(value,{status:"ready",companyId:id,company:{resource_id:id,version_id:version,content_hash:hash,display_name:company.display_name},validAt:valid,knownAt:known});
 assert.equal(JSON.stringify(value).includes("must not"),false);
 assert.match(companyNyxCaption(value),/934174/);assert.match(companyNyxCaption(value),/433237/);
 assert.match(explainCompanyNyx(value),/do not establish financial performance/);
 assert.match(explainCompanyNyx(value),/independently stated times/);
});
test("pending and refused snapshots remove every earlier company pin",()=>{
 for(const state of ["updating","unavailable"]){const value=companyNyxContext(id,company,valid,known,state);assert.deepEqual(value,{companyId:id,status:state});assert.match(explainCompanyNyx(value),/No earlier company version or shell accounting context/);}
 for(const change of [{resource_id:version},{version_id:"invalid"},{content_hash:"missing"},{object_type:"EnterpriseGroup"},{authority_state:"PROPOSED"},{evidence_class:"REFERENCE_TEMPLATE"}])assert.equal(companyNyxContext(id,{...company,...change},valid,known,"ready").status,"unavailable");
 assert.equal(companyNyxContext(id,company,valid,"2026-09-08T04:02:00","ready").status,"unavailable");
});
test("session, company, surface, handoff entry and source-route changes cannot reuse prior readback",()=>{
 const context=ready(),key=JSON.stringify(["token-a","companies",id,"handoff-a"]),readback={key,context};
 assert.equal(companyNyxForSurface(readback,key,id,true),context);
 for(const next of [["token-b","companies",id,"handoff-a"],["token-a","home",id,"handoff-a"],["token-a","companies",id,"handoff-b"]])assert.deepEqual(companyNyxForSurface(readback,JSON.stringify(next),id,true),{companyId:id,status:"updating"});
 assert.equal(companyNyxForSurface(readback,key,id,false),null);
 assert.equal(companyNyxForSurface(readback,key,"",true),null);
 assert.deepEqual(companyNyxForSurface(readback,key,version,true),{companyId:version,status:"updating"});
});
test("explicit source, Trace, resource, map and work selections retain priority over company fallback",()=>{
 const context=ready(),none={source:false,trace:false,resource:false,map:false,work:false,pending:false,refused:false};
 assert.equal(companyNyxFallback(context,none),context);
 for(const field of Object.keys(none))assert.equal(companyNyxFallback(context,{...none,[field]:true}),null);
 assert.equal(companyNyxFallback(null,none),null);
});
test("new company responses cannot mutate references retained for a previous reply",()=>{
 const previous=ready(),before=structuredClone(previous);
 const next=companyNyxContext(id,{...company,version_id:"33333333-3333-4333-8333-333333333333",content_hash:"b".repeat(64),display_name:"Later company name"},valid,"2026-09-09T00:00:00Z","ready");
 assert.notEqual(previous.company.version_id,next.company.version_id);
 assert.deepEqual(previous,before);
 assert.notEqual(previous.company,company);
});
