import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";
import ts from "typescript";
const source=await readFile(new URL("../app/finance-report-reference.ts",import.meta.url),"utf8");
const {financeReportReference}=await import(`data:text/javascript;base64,${Buffer.from(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText).toString("base64")}`);
const result={invocation_id:"retained",status:"SUCCEEDED",output:{contract:"function-result/1",coverage:"RETAINED_SOURCE_POSTINGS_WITH_EXPLICIT_EXCLUSIONS",authority:"GUARDED_POSTED_MOVEMENT_ANALYSIS",current_use_authorized:false,business_effect_authorized:false,posted_movements:{},source_document:{company_id:"company",document_id:"document",scope:{resource_id:"scope"}}}};
test("retained Finance handoff carries source ownership and the original invocation only",()=>{
 assert.deepEqual(financeReportReference(result),{invocationId:"retained",companyId:"company",documentId:"document",scopeId:"scope"});
});
test("generic counts, failed invocations and incomplete source ownership cannot enter Finance",()=>{
 for(const value of [null,{...result,status:"FAILED"},{...result,output:{...result.output,coverage:"QUERY_PAGE_ONLY"}},{...result,output:{...result.output,source_document:{document_id:"document"}}},{...result,output:{...result.output,current_use_authorized:true}}])assert.equal(financeReportReference(value),null);
});
