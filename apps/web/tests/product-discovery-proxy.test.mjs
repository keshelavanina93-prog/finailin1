import assert from "node:assert/strict";
import test from "node:test";
import {loadTypeScript} from "./load-typescript.mjs";
const routes=await loadTypeScript(new URL("../app/api/ontology/[...path]/route.ts",import.meta.url));
test("financial discovery and inspected-plan proxy preserve inputs and reject unintended verbs",async()=>{
 const previous=globalThis.fetch,calls=[];
 globalThis.fetch=async(url,options)=>{calls.push({url,options});return Response.json({retained:true});};
 async function forward(method,path,auth=true){const req=new Request(`http://fixture.invalid/api/ontology/${path}?company_id=company&known_at=2026-09-08T00:00:00.123456Z`,{method,headers:auth?{authorization:"Bearer fixture","Content-Type":"application/json"}:{},...(method==="POST"?{body:JSON.stringify({expected_plan_hash:"a".repeat(64)})}:{})});req.nextUrl=new URL(req.url);return routes[method](req,{params:Promise.resolve({path:path.split("/")})});}
 try{
  assert.equal((await forward("GET","company-financial-results")).status,200);
  assert.ok(calls[0].url.includes("known_at=2026-09-08T00:00:00.123456Z"));
  for(const path of ["transformations/preview","transformations/previewed-runs"]){assert.equal((await forward("POST",path)).status,200);assert.equal((await forward("GET",path)).status,404);}
  assert.equal(JSON.parse(new TextDecoder().decode(calls[2].options.body)).expected_plan_hash,"a".repeat(64));
  assert.equal((await forward("POST","company-financial-results")).status,404);
  assert.equal((await forward("GET","company-financial-results",false)).status,401);
  assert.equal((await forward("POST","transformations/preview",false)).status,401);
  assert.equal(calls.length,3);
 }finally{globalThis.fetch=previous;}
});
