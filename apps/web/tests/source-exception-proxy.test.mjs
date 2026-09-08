import assert from "node:assert/strict";
import test from "node:test";
import {loadTypeScript} from "./load-typescript.mjs";
const routes=await loadTypeScript(new URL("../app/api/ontology/[...path]/route.ts",import.meta.url));

test("source exception proxy admits explicit retention and exact history only",async()=>{
 const previous=globalThis.fetch,calls=[],run="fcr_"+"a".repeat(64);
 const body={company_id:"company",invocation_id:"source",journal_snapshot_at:"2026-09-08T08:00:00.123456Z",expected_reconciliation_receipt_hash:"b".repeat(64),coordinate:"Base!S2"};
 globalThis.fetch=async(url,options)=>{calls.push({url,options});return Response.json({fixture:true});};
 async function forward(method,path,auth=true){const r=new Request(`http://fixture.invalid/api/ontology/${path}`,{method,headers:auth?{authorization:"Bearer fixture"}:{},...(method==="POST"?{body:JSON.stringify(body)}:{})});r.nextUrl=new URL(r.url);return routes[method](r,{params:Promise.resolve({path:path.split("/")})});}
 try{
  assert.equal((await forward("POST","source-exceptions")).status,200);
  assert.deepEqual(JSON.parse(new TextDecoder().decode(calls[0].options.body)),body);
  assert.equal((await forward("GET",`source-exceptions/${run}`)).status,200);
  assert.ok(new URL(calls[1].url).pathname.endsWith(`/source-exceptions/${run}`));
  for(const [method,path] of [["GET","source-exceptions"],["POST",`source-exceptions/${run}`],["GET","source-exceptions/current"],["POST","source-exceptions/approve"],["GET",`source-exceptions/${run.toUpperCase()}`]])assert.equal((await forward(method,path)).status,404);
  assert.equal((await forward("POST","source-exceptions",false)).status,401);
  assert.equal((await forward("GET",`source-exceptions/${run}`,false)).status,401);
  assert.equal(calls.length,2);
 }finally{globalThis.fetch=previous;}
});
