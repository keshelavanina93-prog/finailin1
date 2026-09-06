import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";
import ts from "typescript";
const source=await readFile(new URL("../app/process-graph-model.ts",import.meta.url),"utf8");
const {processLayout}=await import(`data:text/javascript;base64,${Buffer.from(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText).toString("base64")}`);
const step=(id,depends_on=[])=>({id,depends_on,function:"retained-function/1"});
test("process graph retains fork/join dependencies without inventing execution state",()=>{
 const result=processLayout({definition:{nodes:[step("join",["left","right"]),step("left",["root"]),step("right",["root"]),step("root")]},events:[]});
 assert.equal(result.error,"");assert.equal(result.edges.length,4);
 const map=new Map(result.nodes.map(n=>[n.id,n]));assert.ok(map.get("root").x<map.get("left").x);assert.equal(map.get("left").x,map.get("right").x);assert.ok(map.get("left").x<map.get("join").x);assert.equal(map.get("join").state,undefined);
});
test("missing pins, loops, duplicate identities and oversized definitions remain explicit",()=>{
 for(const nodes of [[step("a",["missing"])],[step("a",["b"]),step("b",["a"])],[step("a"),step("a")],Array.from({length:201},(_,i)=>step(String(i)))]){
  const result=processLayout({definition:{nodes},events:[]});assert.ok(result.error);assert.deepEqual(result.nodes,[]);
 }
});
