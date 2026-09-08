import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";
import ts from "typescript";
const source=await readFile(new URL("../app/action-model.ts",import.meta.url),"utf8");
const {commands,workState,workPath,validationSummary,canProposeValidationReport}=await import(`data:text/javascript;base64,${Buffer.from(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText).toString("base64")}`);
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

test("validation uses its retained request and keeps persisted evidence separate from runtime visibility",()=>{
 const id="e34e8cc4-b910-4b99-a247-cc4c17c38676";
 assert.equal(workPath({family:"validation",request_id:id,workflow_id:`ontology-validation:${id}`}),`ontology/external/validation/runs/${id}`);
 assert.throws(()=>workPath({family:"validation",request_id:id,workflow_id:"ontology-validation:other"}),/inconsistent/);
 assert.throws(()=>workPath({family:"validation",workflow_id:`ontology-validation:${id}`}),/incomplete/);
 const run={state:"PUBLISHED",runtime_status:"UNOBSERVABLE",report:{outcome:"CONFORMS"},publication_id:"retained"};
 assert.equal(workState("validation",run),"PUBLISHED");
 assert.equal(validationSummary(run).title,"Selected checks passed");
 assert.match(validationSummary(run).detail,/Accounting authority and certification require their own review/);
 assert.deepEqual(commands("validation",run,["read","ingest","ontology_propose","ontology_review"],"maker"),[]);
});

test("unevaluated, refused and cancelled validations never present a successful coverage conclusion",()=>{
 assert.equal(validationSummary({state:"PUBLISHED",report:{outcome:"NOT_EVALUATED"}}).tone,"warning");
 assert.match(validationSummary({state:"PUBLISHED",report:{outcome:"NOT_EVALUATED"}}).detail,/No conformance conclusion/);
 assert.match(validationSummary({state:"COMPLETED",report:{outcome:"REFUSED"}}).title,/could not be evaluated/);
 assert.equal(validationSummary({state:"CANCELLED",report:{outcome:"CONFORMS"}}).title,"Validation cancelled");
 assert.equal(validationSummary({state:"RUNNING",report:null}).title,"Awaiting a retained result");
 assert.equal(validationSummary({state:"PUBLISHED",report:{outcome:"VIOLATES"}}).title,"Constraints need investigation");
});

test("report preparation requires published evidence and explicit permissions, never infers approval",()=>{
 const permissions=["read","ontology_read","ontology_propose"];
 const run={state:"PUBLISHED",report:{outcome:"VIOLATES"},publication_id:"retained"};
 assert.equal(canProposeValidationReport(run,permissions),true);
 for(const missing of permissions)assert.equal(canProposeValidationReport(run,permissions.filter(p=>p!==missing)),false);
 for(const state of ["INTENT_RETAINED","RUNNING","COMPLETED","CANCELLED"])assert.equal(canProposeValidationReport({...run,state},permissions),false);
 assert.equal(canProposeValidationReport({...run,publication_id:null},permissions),false);
 assert.equal(canProposeValidationReport({...run,report:null},permissions),false);
});
