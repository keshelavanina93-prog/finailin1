import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import ts from "typescript";
const source=readFileSync(new URL("../app/company-360-descriptor.ts",import.meta.url),"utf8");
const {companySnapshot,company360Descriptor}=await import(`data:text/javascript;base64,${Buffer.from(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText).toString("base64")}`);
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
