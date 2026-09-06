import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";
import ts from "typescript";
const source=await readFile(new URL("../app/action-model.ts",import.meta.url),"utf8");
const {commands,workState,workPath}=await import(`data:text/javascript;base64,${Buffer.from(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText).toString("base64")}`);
test("workbench never offers source review to the maker or infers runtime success from retained output",()=>{
 const run={actor_id:"maker",execution:{state:"WAITING_REVIEW"}};
 assert.deepEqual(commands("source",run,["review"],"maker"),[]);
 assert.deepEqual(commands("source",run,["review"],"checker"),["complete"]);
 assert.equal(workState("source",{events:[{state:"PUBLISHED"}],runtime_status:"UNOBSERVABLE"}),"UNOBSERVABLE");
 assert.deepEqual(commands("source",{runtime_status:"UNOBSERVABLE"},["ingest","review"],"checker"),[]);
});
test("family-specific controls never route schedule or proposal commands through source orchestration",()=>{
 assert.deepEqual(commands("monitor",{runtime:{state:"ENABLED"}},["ingest"],"maker"),["pause"]);
 assert.deepEqual(commands("ontology",{state:"PUBLISHED"},["ontology_propose"],"maker"),[]);
 assert.deepEqual(commands("ontology",{state:"PREPARED"},["ontology_propose"],"maker"),["resume"]);
 assert.equal(workPath({family:"monitor",workflow_id:"rgm_a"}),"ontology/regulation/monitors/rgm_a");
 assert.equal(workPath({family:"ontology",workflow_id:"opa_a"}),"ontology/operations/opa_a");
});
