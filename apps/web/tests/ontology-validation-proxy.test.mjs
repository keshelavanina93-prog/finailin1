import assert from "node:assert/strict";
import test from "node:test";
import {loadTypeScript} from "./load-typescript.mjs";

const {GET,POST}=await loadTypeScript(new URL("../app/api/ontology/[...path]/route.ts",import.meta.url));
const id="300ea85d-0f96-4c93-8ae8-c51855c8f40d";
const path=`external/validation/runs/${id}`;
const context=route=>({params:Promise.resolve({path:route.split("/")})});
function request(route,method="GET",body,auth=true){
 const url=new URL(`http://localhost/api/ontology/${route}`);
 const result=new Request(url,{method,body,headers:auth?{authorization:"Bearer synthetic-validator"}:{}});
 result.nextUrl=url;return result;
}

test("validation inspection forwards exact request and credential without changing retained evidence",async t=>{
 const evidence={workflow_id:`ontology-validation:${id}`,state:"PUBLISHED",runtime_status:"UNOBSERVABLE"};
 let calls=0;
 t.mock.method(globalThis,"fetch",async(url,options)=>{
  calls++;assert.ok(url.endsWith(`/v1/ontology/${path}`));assert.equal(options.method,"GET");
  assert.equal(options.headers.Authorization,"Bearer synthetic-validator");assert.equal(options.cache,"no-store");
  assert.equal(options.body,undefined);return Response.json(evidence);
 });
 const response=await GET(request(path),context(path));
 assert.equal(response.status,200);assert.deepEqual(await response.json(),evidence);
 assert.equal(response.headers.get("cache-control"),"no-store");assert.equal(calls,1);
});

test("report preparation forwards exact body and preserves the upstream authority refusal",async t=>{
 t.mock.method(globalThis,"fetch",async(url,options)=>{
  assert.ok(url.endsWith(`/v1/ontology/${path}/report-proposals`));assert.equal(options.method,"POST");
  assert.equal(options.headers.Authorization,"Bearer synthetic-validator");
  assert.equal(new TextDecoder().decode(options.body),'{}');
  return Response.json({detail:"Independent ontology authority is required"},{status:403});
 });
 const response=await POST(request(`${path}/report-proposals`,"POST","{}"),context(`${path}/report-proposals`));
 assert.equal(response.status,403);assert.equal((await response.json()).detail,"Independent ontology authority is required");
});

test("validation proxy permits no adjacent commands, malformed identity or method substitution",async t=>{
 t.mock.method(globalThis,"fetch",()=>assert.fail("A refused request must not contact the backend"));
 for(const [method,route] of [
  ["POST",path],["GET",`${path}/report-proposals`],["POST",`${path}/cancel`],
  ["POST","external/validation/runs"],["POST","external/profiles/proposals"],
  ["POST","external/index/rebuild"],["GET",`${path}/events`],
  ["GET","external/validation/runs/a-b-c"],["GET",`${path}0`],
  ["GET",`${path}/../report-proposals`],["POST",`${path}/report-proposals/extra`],
 ]){
  const response=await (method==="GET"?GET:POST)(request(route,method,method==="POST"?"{}":undefined),context(route));
  assert.equal(response.status,404,`${method} ${route}`);
 }
 assert.equal((await GET(request(path,"GET",undefined,false),context(path))).status,401);
 assert.equal((await POST(request(`${path}/report-proposals`,"POST","x".repeat(1_000_001)),context(`${path}/report-proposals`))).status,413);
});

test("an unavailable validation backend stays unavailable",async t=>{
 t.mock.method(globalThis,"fetch",async()=>{throw Error("offline");});
 const response=await GET(request(path),context(path));
 assert.equal(response.status,503);assert.deepEqual(await response.json(),{detail:"Ontology service unavailable"});
});
