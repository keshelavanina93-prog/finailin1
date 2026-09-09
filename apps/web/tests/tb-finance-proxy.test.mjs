import assert from "node:assert/strict";
import test from "node:test";
import {loadTypeScript} from "./load-typescript.mjs";

const routes=await loadTypeScript(new URL("../app/api/ontology/[...path]/route.ts",import.meta.url));

function request(method,path,auth=true){
  const request=new Request(`http://fixture.invalid/api/ontology/${path}`,{
    method,
    headers:auth?{authorization:"Bearer fixture"}:{},
    ...(method==="POST"?{body:JSON.stringify({receipt_ids:[]})}:{}),
  });
  request.nextUrl=new URL(request.url);
  return request;
}

test("TB Finance draft proxy forwards only its mounted read and write routes",async()=>{
  const previous=globalThis.fetch;
  const calls=[];
  globalThis.fetch=async(url,options)=>{calls.push({url,options});return Response.json({fixture:true});};
  const context=path=>({params:Promise.resolve({path:path.split("/")})});
  try{
    for(const [method,path] of [
      ["GET","finance/tb/sources"],
      ["GET","finance/tb/contract"],
      ["GET","finance/tb/runs/fcr_"+"a".repeat(64)],
      ["GET","finance/tb/diagnostics"],
      ["POST","finance/tb/draft"],
      ["POST","finance/tb/export"],
      ["POST","finance/tb/command"],
    ]){
      assert.equal((await routes[method](request(method,path),context(path))).status,200);
    }
    assert.equal(calls.length,7);
    assert.ok(calls.every(({url})=>String(url).includes("/v1/ontology/finance/tb/")));
    for(const [method,path] of [
      ["GET","finance/tb/draft"],
      ["POST","finance/tb/sources"],
      ["GET","finance/tb/runs/not-a-run"],
    ]) assert.equal((await routes[method](request(method,path),context(path))).status,404);
    assert.equal((await routes.GET(request("GET","finance/tb/sources",false),context("finance/tb/sources"))).status,401);
    assert.equal(calls.length,7);
  }finally{globalThis.fetch=previous;}
});
