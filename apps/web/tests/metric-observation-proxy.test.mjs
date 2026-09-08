import assert from "node:assert/strict";
import test from "node:test";
import {loadTypeScript} from "./load-typescript.mjs";
const routes=await loadTypeScript(new URL("../app/api/ontology/[...path]/route.ts",import.meta.url));

test("metric observation proxy forwards exact evidence requests and immutable reads only",async()=>{
 const previous=globalThis.fetch,calls=[],id="fcr_"+"a".repeat(64);
 const body={metric:{resource_id:"metric",version_id:"version",content_hash:"b".repeat(64)},invocation_id:"invocation",expected_receipt_hash:"c".repeat(64),valid_at:"2025-01-31T00:00:00.123456Z",known_at:"2026-09-08T08:00:00.654321Z"};
 globalThis.fetch=async(url,options)=>{calls.push({url,options});return Response.json({fixture:true});};
 function request(method,path,auth=true){const value=new Request(`http://fixture.invalid/api/ontology/${path}`,{method,headers:auth?{authorization:"Bearer fixture","Content-Type":"application/json"}:{},...(method==="POST"?{body:JSON.stringify(body)}:{})});value.nextUrl=new URL(value.url);return value;}
 async function forward(method,path,auth=true){return routes[method](request(method,path,auth),{params:Promise.resolve({path:path.split("/")})});}
 try{
  assert.equal((await forward("POST","metrics/observations")).status,200);
  assert.deepEqual(JSON.parse(new TextDecoder().decode(calls[0].options.body)),body);
  assert.equal(calls[0].options.headers.Authorization,"Bearer fixture");assert.equal(calls[0].options.cache,"no-store");
  assert.equal((await forward("GET",`metrics/observations/${id}`)).status,200);
  assert.ok(new URL(calls[1].url).pathname.endsWith(`/metrics/observations/${id}`));
  for(const [method,path] of [["GET","metrics/observations"],["POST",`metrics/observations/${id}`],["GET","metrics/observations/current"],["POST","metrics/observations/publish"],["GET",`metrics/observations/${id.toUpperCase()}`]])assert.equal((await forward(method,path)).status,404);
  assert.equal((await forward("POST","metrics/observations",false)).status,401);
  assert.equal((await forward("GET",`metrics/observations/${id}`,false)).status,401);
  assert.equal(calls.length,2);
 }finally{globalThis.fetch=previous;}
});
