import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";
import ts from "typescript";
async function load(path) {
  const source=await readFile(new URL(path,import.meta.url),"utf8");
  const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext}});
  return import(`data:text/javascript;base64,${Buffer.from(compiled.outputText).toString("base64")}`);
}
const {GET}=await load("../app/api/readiness/route.ts");
const {acceptedCompanies,belongsToCompany,workItems}=await load("../app/g8-model.ts");
test("readiness never queries storage for missing or denied identity",async t=>{
  let calls=0;
  t.mock.method(globalThis,"fetch",async()=>{calls++;return Response.json({detail:"Denied"},{status:403});});
  assert.equal((await GET(new Request("http://local/api/readiness"))).status,401);
  assert.equal(calls,0);
  assert.equal((await GET(new Request("http://local/api/readiness",{headers:{Authorization:"Bearer scoped"}}))).status,403);
  assert.equal(calls,1);
});
test("readiness preserves partial outage as an observed 503 without caching",async t=>{
  let calls=0;
  t.mock.method(globalThis,"fetch",async(url,options)=>{
    calls++; assert.equal(options.cache,"no-store");
    if(url.endsWith("/session")){assert.equal(options.headers.Authorization,"Bearer scoped");return Response.json({actor_id:"reader"});}
    return Response.json({status:"unavailable",database:"ready",schema:"ready",evidence_store:"unavailable"},{status:503});
  });
  const response=await GET(new Request("http://local/api/readiness",{headers:{Authorization:"Bearer scoped"}}));
  assert.equal(response.status,503);assert.equal(calls,2);assert.equal(response.headers.get("Cache-Control"),"no-store");
  assert.equal((await response.json()).evidence_store,"unavailable");
});
test("company context cannot treat a revoked identity or operating domain as a company",()=>{
  const accepted={resource_id:"gas",object_type:"LegalEntity",authority_state:"APPROVED",evidence_class:"SOURCE_BOUND"};
  assert.deepEqual(acceptedCompanies([accepted,{...accepted,evidence_class:"USER_ASSERTED"},{...accepted,evidence_class:"REFERENCE_TEMPLATE"},{...accepted,authority_state:"REVOKED"},{...accepted,object_type:"OperatingDomain"}]),[accepted]);
  assert.equal(belongsToCompany({resource_id:"asset",attributes:{company_id:"petroleum"}},"gas"),false);
  assert.equal(belongsToCompany({resource_id:"asset",attributes:{legal_entity_id:"gas"}},"gas"),true);
});
test("work ordering prioritizes failed source rows and pending review over accepted history",()=>{
  const source={receipt_id:"source",filename:"actual.csv",review_state:"PENDING",ingested_at:"2026-09-01",reject_count:2};
  const accepted={...source,receipt_id:"newer",review_state:"APPROVED",reject_count:0,ingested_at:"2026-09-05"};
  const proposal={proposal_id:"proposal",title:"Change",decision:"PENDING",created_at:"2026-09-04",rationale:"Review semantic change"};
  const items=workItems([accepted,source],[proposal]);
  assert.deepEqual(items.map(item=>item.id),["source","proposal","newer"]);
  assert.match(items[0].reason,/2 source rows failed/);assert.equal(items[1].reason,proposal.rationale);
});
