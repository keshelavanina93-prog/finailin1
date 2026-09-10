import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {createRequire} from "node:module";
import vm from "node:vm";
import test from "node:test";
import ts from "typescript";
import {loadTypeScript} from "./load-typescript.mjs";
const require=createRequire(new URL("../package.json",import.meta.url));
const state=await loadTypeScript(new URL("../app/semantic-analysis-state.ts",import.meta.url));
const source=await readFile(new URL("../app/semantic-analysis-workspace.tsx",import.meta.url),"utf8");
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
const compiledModule={exports:{}};
// Exercise the exported, mounted evidence table itself without starting a browser.
vm.runInNewContext(compiled,{module:compiledModule,exports:compiledModule.exports,require(name){
 if(name==="react"||name==="react/jsx-runtime")return require(name);
 if(name==="next/dynamic")return {default:()=>()=>null};
 if(name==="./semantic-analysis-state")return state;
 return {};
}});
const {EvidenceCells}=compiledModule.exports;
const pin={resource_id:"11111111-1111-4111-8111-111111111111",version_id:"22222222-2222-4222-8222-222222222222",content_hash:"a".repeat(64)};
function text(value,advanced=false){
 if(Array.isArray(value))return value.map(v=>text(v,advanced)).join(" ").replace(/\s+/g," ").trim();
 if(value==null||typeof value==="boolean")return "";
 if(typeof value!=="object")return String(value);
 const children=value.props?.children;
 if(value.type==="details"&&!advanced)return text((Array.isArray(children)?children:[children]).filter(v=>v?.type==="summary"),false);
 return text(children,advanced);
}
const cell=(label,value,extra={})=>({label,value,coordinate:null,formula:null,...extra});
test("typed references expose readable labels while exact values and pins require Advanced",()=>{
 const contributor={basis:"CANONICAL_DEFINITION",label:"Accepted journal",reference:pin,cells:[cell("Journal line version",`${pin.resource_id}@${pin.version_id}`,{reference:pin})]};
 const original=JSON.stringify(contributor),tree=EvidenceCells({contributor}),primary=text(tree),expanded=text(tree,true);
 assert.match(primary,/Advanced · Journal line version/);
 for(const exact of [pin.resource_id,pin.version_id,pin.content_hash]){assert.equal(primary.includes(exact),false);assert.ok(expanded.includes(exact));}
 assert.equal(JSON.stringify(contributor),original);
});
test("canonical business facts stay visible, including false, zero, null and empty text",()=>{
 const contributor={basis:"CANONICAL_DEFINITION",label:"Account",reference:pin,cells:[cell("Account code","0012.01"),cell("Description","შემოსავალი / Доход / Revenue"),cell("Units",0),cell("Enabled",false),cell("Optional",null),cell("Note","")]};
 const primary=text(EvidenceCells({contributor}));
 for(const value of ["0012.01","შემოსავალი / Доход / Revenue","0","false","Recorded null","Empty text"])assert.ok(primary.includes(value));
});
test("original source values, coordinates and formulas remain visible",()=>{
 const contributor={basis:"ORIGINAL_SOURCE",label:"Retained cells",reference:pin,cells:[cell("Amount","731.9700",{coordinate:"Base!S2",formula:"AD2-S2"}),cell("Absent",null)]};
 const primary=text(EvidenceCells({contributor}));
 for(const value of ["731.9700","Base!S2","Formula: AD2-S2","No literal value retained"])assert.ok(primary.includes(value));
});
test("presentation depends only on typed metadata, never label or value patterns",()=>{
 for(const reference of [undefined,null]){
  const contributor={basis:"CANONICAL_DEFINITION",label:"Business object",reference:pin,cells:[cell("Journal line version",pin.resource_id,{reference})]};
  assert.ok(text(EvidenceCells({contributor})).includes(pin.resource_id));
 }
 const contributor={basis:"ORIGINAL_SOURCE",label:"Different source",reference:pin,cells:[cell("Unrelated label","technical payload",{reference:pin})]};
 assert.equal(text(EvidenceCells({contributor})).includes("technical payload"),false);
});
