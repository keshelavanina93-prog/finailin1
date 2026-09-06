import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";
import ts from "typescript";
const source=await readFile(new URL("../app/history-model.ts",import.meta.url),"utf8");
const {compareVersions}=await import(`data:text/javascript;base64,${Buffer.from(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText).toString("base64")}`);
const version=attributes=>({display_name:"Retained source",authority_state:"APPROVED",evidence_class:"OBSERVED",valid_from:"2024-01-01",valid_to:null,attributes});
test("history distinguishes absent, null and exact decimal strings without arithmetic or coercion",()=>{
  const before=version({amount:"9007199254740993.01",zero:0,missing:null});
  const after=version({amount:"9007199254740993.02",zero:"0"});
  const rows=compareVersions(before,after).filter(r=>r.changed);
  assert.deepEqual(rows.map(r=>r.path),[["amount"],["missing"],["zero"]]);
  assert.deepEqual(rows[1].before,{present:true,value:null});
  assert.equal(rows[1].after.present,false);
  assert.equal(rows[0].before.value,"9007199254740993.01");
});
test("history ignores object key order and preserves array order and nested field paths",()=>{
  assert.equal(compareVersions(version({nested:{b:2,a:1}}),version({nested:{a:1,b:2}})).some(r=>r.changed),false);
  const rows=compareVersions(version({members:[{name:"A"},{name:"B"}]}),version({members:[{name:"B"},{name:"A"}]})).filter(r=>r.changed);
  assert.deepEqual(rows.map(r=>r.path),[["members","Item 1","name"],["members","Item 2","name"]]);
});
