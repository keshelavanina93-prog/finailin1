import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";
import ts from "typescript";
const source=await readFile(new URL("../app/source-adoption-types.ts",import.meta.url),"utf8");
const {checkedPrepared,checkedSnapshot,requestKey}=await import(`data:text/javascript;base64,${Buffer.from(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText).toString("base64")}`);
const pin=id=>({resource_id:id,version_id:`${id}-version`,content_hash:"a".repeat(64)});
const snapshot={binding:pin("binding"),scope:pin("scope"),evidence:pin("evidence"),company:pin("company"),chart:pin("chart"),period:pin("period"),period_starts_on:"2025-01-01",period_ends_on:"2025-01-31",observed_from:"2025-01-01",observed_through:"2025-01-31",source_sha256:"a".repeat(64),schema_sha256:"b".repeat(64),document_id:"retained-document",worksheet:"Base",source_profile:"seg_expense_base",source_rows:2,missing_amount_count:1,missing_amount_coordinates:["Base!S2"],coverage_state:"UNESTABLISHED",meaning:{amount_semantics:"DEBIT_CREDIT"}};
const selection={family_key:"family",source_system:"1C",display_name:"Reviewed family",baseline_binding:pin("binding"),rationale:"Explicit reviewed reason"};
const prepared={resource_id:"family",object_type:"SourceFamily",display_name:"Reviewed family",attributes:{company_id:"company",definition:{version:1,selection,baseline:snapshot}},accounting_aggregation_authorized:false};
test("review retains server snapshot without interpreting compatibility or amounts",()=>{
 assert.equal(checkedPrepared(prepared,selection,"company"),prepared);
 assert.equal(checkedSnapshot(snapshot,"company"),snapshot);
 assert.equal(requestKey({b:2,a:1}),requestKey({a:1,b:2}));
});
test("changed company, source pin, selection and aggregation authority fail closed",()=>{
 assert.throws(()=>checkedSnapshot(snapshot,"another-company"));
 assert.throws(()=>checkedPrepared(prepared,{...selection,baseline_binding:pin("changed")},"company"));
 assert.throws(()=>checkedPrepared(prepared,{...selection,rationale:"Different reviewed intent"},"company"));
 assert.throws(()=>checkedPrepared({...prepared,accounting_aggregation_authorized:true},selection,"company"));
 assert.throws(()=>checkedSnapshot({...snapshot,source_rows:1,missing_amount_count:2},"company"));
});
test("successor comparison carries its own exact period and binding",()=>{
 const successor={...snapshot,binding:pin("successor"),scope:pin("successor-scope"),period:pin("february"),period_starts_on:"2025-02-01",period_ends_on:"2025-02-28",observed_from:"2025-02-01",observed_through:"2025-02-28"};
 const request={family:pin("family"),predecessor_binding:snapshot.binding,successor_binding:successor.binding,predecessor_adoption:null,policy:"DISJOINT_PERIOD_ADDITION",rationale:"Later reviewed source"};
 const value={...prepared,object_type:"SourceSnapshotAdoption",attributes:{company_id:"company",definition:{version:1,selection:request,family:pin("family"),predecessor:snapshot,successor}}};
 assert.equal(checkedPrepared(value,request,"company").attributes.definition.successor.period.resource_id,"february");
 assert.throws(()=>checkedPrepared({...value,attributes:{...value.attributes,definition:{...value.attributes.definition,successor:{...successor,binding:snapshot.binding}}}},request,"company"));
});
