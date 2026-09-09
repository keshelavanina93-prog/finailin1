import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import ts from "typescript";
const source=readFileSync(new URL("../app/api/ontology/[...path]/route.ts",import.meta.url),"utf8").replace('import { backendBaseUrl } from "../../backend";','const backendBaseUrl=()=>"http://fixture.invalid";');
const route=await import(`data:text/javascript;base64,${Buffer.from(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText).toString("base64")}`);
test("only exact GET attempt and disposition paths pass proxy and retain scope query",async()=>{
 const original=globalThis.fetch,calls=[];globalThis.fetch=async(url,options)=>{calls.push({url,options});return Response.json({fixture:true});};
 try{const id="11111111-1111-4111-8111-111111111111",path=`company-journals/production/attempts/${id}`;
  for(const suffix of ["","/dispositions"]){const request={method:"GET",headers:new Headers({authorization:"Bearer fixture"}),nextUrl:{search:`?company_id=${id}`}};assert.equal((await route.GET(request,{params:Promise.resolve({path:(path+suffix).split("/")})})).status,200);assert.ok(calls.at(-1).url.endsWith(`${suffix}?company_id=${id}`));}
  for(const [method,target] of [["POST",path],["POST",`${path}/dispositions`],["GET",`${path}/review`],["GET","company-journals/production/attempts/bad/dispositions"]])assert.equal((await route[method]({method,headers:new Headers({authorization:"Bearer fixture"}),nextUrl:{search:""}},{params:Promise.resolve({path:target.split("/")})})).status,404);
  assert.equal(calls.length,2);
 }finally{globalThis.fetch=original;}
});
