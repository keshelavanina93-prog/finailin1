import assert from "node:assert/strict";
import test from "node:test";
import {readFile} from "node:fs/promises";
import {loadTypeScript} from "./load-typescript.mjs";
const {companyMapScope}=await loadTypeScript(new URL("../app/company-map-scope.ts",import.meta.url));

test("an unresolved or foreign company never broadens to workspace geography",()=>{
  for(const consent of [false,true])for(const ready of [false,true]){
    assert.equal(companyMapScope("selected",undefined,ready,consent),"unresolved");
    assert.equal(companyMapScope("selected","other",ready,consent),"unresolved");
  }
  assert.equal(companyMapScope("selected","selected",false,true),"unresolved");
  assert.equal(companyMapScope("selected","selected",true,false),"company");
});
test("workspace assets require an explicit choice with no selected company",()=>{
  assert.equal(companyMapScope("",undefined,true,false),"choose");
  assert.equal(companyMapScope("",undefined,false,false),"choose");
  assert.equal(companyMapScope("",undefined,true,true),"workspace");
});
test("the shell preserves raw scope and isolates map lenses, bounds and time by company and session",async()=>{
  const source=await readFile(new URL("../app/g8-workspace.tsx",import.meta.url),"utf8");
  assert.match(source,/mapStateScope=JSON\.stringify\(\[token,companyId\]\)/);
  assert.match(source,/storedMapState\?\.scope===mapStateScope\?storedMapState\.state:initialMapState/);
  assert.match(source,/setStoredMapState\(\{scope:mapStateScope,state\}\)/);
  assert.match(source,/mapProps=\{token,selection:mapSelection,companyId:companyId\|\|undefined/);
  assert.match(source,/mapScope==="company"\|\|mapScope==="workspace"/);
  assert.match(source,/companyMapScope\(companyId,currentCompany\?\.resource_id,companyDirectory\.data!==null,workspaceMapSession===token\)/);
});
