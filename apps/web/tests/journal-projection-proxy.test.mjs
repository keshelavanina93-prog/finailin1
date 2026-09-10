import test from "node:test";
import assert from "node:assert/strict";
import {loadTypeScript} from "./load-typescript.mjs";
const {POST,GET}=await loadTypeScript(new URL("../app/api/ontology/[...path]/route.ts",import.meta.url));
function request(method,auth=true){const request=new Request("http://g8.invalid/api/ontology/company-journals/reconciliation/projection?snapshot_at=2026-09-08T08%3A00%3A00Z",{method,headers:auth?{Authorization:"Bearer test-only", "Content-Type":"application/json"}:{},...method==="POST"?{body:JSON.stringify({company_id:"company",invocation_id:"invocation"})}:{}});request.nextUrl=new URL(request.url);return request;}
test("only the authenticated read-only projection route is forwarded with its fixed snapshot",async()=>{
 const previous=globalThis.fetch;let forwarded=null;
 globalThis.fetch=async(url,options)=>{forwarded={url,options};return Response.json({retained:true});};
 try{
  const response=await POST(request("POST"),{params:Promise.resolve({path:["company-journals","reconciliation","projection"]})});
  assert.equal(response.status,200);assert.equal(forwarded.options.method,"POST");assert.equal(new URL(forwarded.url).searchParams.get("snapshot_at"),"2026-09-08T08:00:00Z");assert.equal(forwarded.options.headers.Authorization,"Bearer test-only");assert.equal(forwarded.options.cache,"no-store");
  forwarded=null;assert.equal((await POST(request("POST",false),{params:Promise.resolve({path:["company-journals","reconciliation","projection"]})})).status,401);assert.equal(forwarded,null);
  for(const path of [["company-journals","production","proposals"],["company-journals","production","preview"],["company-journals","reconciliation","unexpected"]])assert.equal((await POST(request("POST"),{params:Promise.resolve({path})})).status,404);
  assert.equal((await GET(request("GET"),{params:Promise.resolve({path:["company-journals","reconciliation","projection"]})})).status,404);assert.equal(forwarded,null);
 }finally{globalThis.fetch=previous;}
});

test("metrics preserve the exact request and permit only authenticated read POST",async()=>{
 const original=globalThis.fetch,body={company_id:"company",invocation_id:"invocation",snapshot_at:"2026-09-08T08:00:00.123456Z",expected_reconciliation_sha256:"a".repeat(64),expected_result_sha256:"b".repeat(64)};
 let forwarded=null;
 globalThis.fetch=async(url,options)=>{forwarded={url,options};return Response.json({retained:true});};
 function metricRequest(method,auth=true){const req=new Request("http://g8.invalid/api/ontology/company-journals/reconciliation/metrics",{method,headers:auth?{Authorization:"Bearer test-only","Content-Type":"application/json"}:{},...(method==="POST"?{body:JSON.stringify(body)}:{})});req.nextUrl=new URL(req.url);return req;}
 const context={params:Promise.resolve({path:["company-journals","reconciliation","metrics"]})};
 try{
  assert.equal((await POST(metricRequest("POST"),context)).status,200);
  assert.equal(new URL(forwarded.url).pathname,"/v1/ontology/company-journals/reconciliation/metrics");
  assert.deepEqual(JSON.parse(new TextDecoder().decode(forwarded.options.body)),body);assert.equal(forwarded.options.cache,"no-store");
  forwarded=null;assert.equal((await POST(metricRequest("POST",false),context)).status,401);assert.equal(forwarded,null);
  assert.equal((await GET(metricRequest("GET"),context)).status,404);assert.equal(forwarded,null);
  assert.equal((await POST(metricRequest("POST"),{params:Promise.resolve({path:["company-journals","reconciliation","metrics","publish"]})})).status,404);assert.equal(forwarded,null);
 }finally{globalThis.fetch=original;}
});
