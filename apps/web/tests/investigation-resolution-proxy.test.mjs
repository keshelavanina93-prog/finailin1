import assert from "node:assert/strict";
import test from "node:test";
import {loadTypeScript} from "./load-typescript.mjs";
const routes=await loadTypeScript(new URL("../app/api/ontology/[...path]/route.ts",import.meta.url));
test("resolution proxy preserves exact intent and read-only reconciliation query",async()=>{
 const previous=globalThis.fetch,calls=[],id="12345678-1234-4234-8234-123456789abc",pin={resource_id:id,version_id:id,content_hash:"a".repeat(64)};
 const body={request_id:id,finding:pin,investigation:pin,matched_exception_run_id:"fcr_"+"b".repeat(64),rationale:"Review this compatible journal match"};
 globalThis.fetch=async(url,options)=>{calls.push({url,options});return Response.json({fixture:true});};
 async function forward(method,path,auth=true,query=""){const r=new Request(`http://fixture.invalid/api/ontology/${path}${query}`,{method,headers:auth?{authorization:"Bearer fixture"}:{},...(method==="POST"?{body:JSON.stringify(body)}:{})});r.nextUrl=new URL(r.url);return routes[method](r,{params:Promise.resolve({path:path.split("/")})});}
 try{
  assert.equal((await forward("POST","operations/investigation-resolutions")).status,200);
  assert.deepEqual(JSON.parse(new TextDecoder().decode(calls[0].options.body)),body);
  const path=`company-journals/reconciliation/source/${id}`,query=`?company_id=${id}&snapshot_at=2026-09-08T17%3A00%3A00.123456Z`;
  assert.equal((await forward("GET",path,true,query)).status,200);
  assert.equal(new URL(calls[1].url).search,query);
  assert.equal(calls[1].options.method,"GET");
  for(const [method,route] of [["GET","operations/investigation-resolutions"],["POST","operations/investigation-resolutions/approve"],["POST","operations/investigation-resolutions/post-journal"],["POST",path],["GET","company-journals/reconciliation/source/current"]])assert.equal((await forward(method,route)).status,404);
  assert.equal((await forward("POST","operations/investigation-resolutions",false)).status,401);
  assert.equal((await forward("GET",path,false)).status,401);
  assert.equal(calls.length,2);
 }finally{globalThis.fetch=previous;}
});
