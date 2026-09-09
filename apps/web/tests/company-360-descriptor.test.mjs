import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import ts from "typescript";
const timeSource=readFileSync(new URL("../app/definition-restoration-time.ts",import.meta.url),"utf8");
const source=readFileSync(new URL("../app/company-360-descriptor.ts",import.meta.url),"utf8").replace('import {restorationInstant} from "./definition-restoration-time";',timeSource);
const {companySnapshot,company360Descriptor,companyCutoffs,restoreCompanyCutoffs}=await import(`data:text/javascript;base64,${Buffer.from(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText).toString("base64")}`);
const company={resource_id:"11111111-1111-4111-8111-111111111111",version_id:"22222222-2222-4222-8222-222222222222",object_type:"LegalEntity",authority_state:"APPROVED",evidence_class:"AUTHENTIC_SOURCE"};
const time="2026-09-08T01:00:00Z";
const context={company,relationships:[],structural_resources:[],ledgers:[],accounting_sources:[],licence_evidence:[],disclosures:[],dimensions:[]};
test("Company360 refuses wrong company, unreviewed templates and ambiguous snapshot times",()=>{
 const response={context,valid_at:time,known_at:time};
 assert.equal(companySnapshot(response,company.resource_id).knownAt,time);
 assert.throws(()=>companySnapshot(response,"another-company"));
 for(const change of [{object_type:"EnterpriseGroup"},{authority_state:"PENDING"},{evidence_class:"REFERENCE_TEMPLATE"}])assert.throws(()=>companySnapshot({...response,context:{...context,company:{...company,...change}}},company.resource_id));
 for(const known_at of ["2026-09-08T01:00:00","invalid",null])assert.throws(()=>companySnapshot({...response,known_at},company.resource_id));
});
test("operating presence requires an explicit relationship at the exact version",()=>{
 const asset={...company,resource_id:"asset",version_id:"asset-v2",object_type:"Facility"};
 assert.equal(company360Descriptor({...context,structural_resources:[asset]},time,time).operatingResources.length,0);
 const relation={kind:"OPERATES",record:{...company,object_type:"Relationship"},source:company,target:{...asset,version_id:"asset-v1"}};
 assert.equal(company360Descriptor({...context,structural_resources:[asset],relationships:[relation]},time,time).operatingResources.length,0);
 const result=company360Descriptor({...context,structural_resources:[asset],relationships:[{...relation,target:asset}]},time,time);
 assert.equal(result.operatingResources[0],asset);
 assert.equal(result.connections[0].kind,"OPERATES");
 assert.equal(result.knownAt,time);
});

test("saved company cutoffs retain only aware references for the exact company",()=>{
 const cutoffs={validAt:"2026-09-07T18:29:53.123456+04:00",knownAt:time};
 const saved={companyId:company.resource_id,cutoffs:{...cutoffs,token:"must not restore",context:{secret:true}}};
 assert.deepEqual(restoreCompanyCutoffs(saved,company.resource_id),cutoffs);
 assert.equal(restoreCompanyCutoffs(saved,"another-company"),null);
 for(const invalid of [null,{}, {validAt:time}, {validAt:"2026-09-08T01:00:00",knownAt:time}, {validAt:"2026-02-30T01:00:00Z",knownAt:time},{validAt:time,knownAt:"2026-09-08T24:00:00Z"}])assert.equal(companyCutoffs(invalid),null);
});

test("requested snapshots compare timezone-normalized instants without losing microseconds",()=>{
 const requested={validAt:"2026-09-07T18:29:53.123456+04:00",knownAt:"2026-09-08T01:00:00.123456Z"};
 const response={context,valid_at:"2026-09-07T14:29:53.123456Z",known_at:"2026-09-08T05:00:00.123456+04:00"};
 assert.equal(companySnapshot(response,company.resource_id,requested).validAt,response.valid_at);
 assert.throws(()=>companySnapshot({...response,known_at:"2026-09-08T05:00:00.123457+04:00"},company.resource_id,requested));
 assert.throws(()=>companySnapshot({...response,valid_at:"2026-09-07T14:29:53.123455Z"},company.resource_id,requested));
 assert.throws(()=>companySnapshot(response,company.resource_id,{validAt:time,knownAt:time}));
});
