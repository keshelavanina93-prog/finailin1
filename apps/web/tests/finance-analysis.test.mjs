import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";
import ts from "typescript";
const source=await readFile(new URL("../app/finance-analysis-query.ts",import.meta.url),"utf8");
const {compileAnalysis,emptySelection}=await import(`data:text/javascript;base64,${Buffer.from(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText).toString("base64")}`);
const fields={legal_entity_id:{kind:"reference",target_type:"LegalEntity"},debit_account_id:{kind:"reference",target_type:"LocalAccount"},credit_account_id:{kind:"reference",target_type:"LocalAccount"},posting_date:{kind:"date"},amount:{kind:"decimal"}};
test("either-side account selection keeps company and date constraints outside the OR",()=>{
 const q=compileAnalysis("company",{...emptySelection,account:"account",from:"2025-01-01",to:"2025-01-31"},fields);
 assert.deepEqual(q.filters,[{field:"legal_entity_id",operator:"eq",value:"company"},{field:"posting_date",operator:"gte",value:"2025-01-01"},{field:"posting_date",operator:"lte",value:"2025-01-31"}]);
 assert.deepEqual(q.filter_expression,{op:"any",conditions:[{field:"debit_account_id",operator:"eq",value:"account"},{field:"credit_account_id",operator:"eq",value:"account"}]});
 assert.deepEqual(q.traversal,[]);
});
test("single-side query and precise source threshold are sent without numeric coercion",()=>{
 const q=compileAnalysis("company",{...emptySelection,account:"account",side:"credit",minimum:"9007199254740993.00100"},fields);
 assert.equal(q.filter_expression,undefined);
 assert.equal(q.filters[1].value,"9007199254740993.00100");
 assert.deepEqual(q.filters[2],{field:"credit_account_id",operator:"eq",value:"account"});
});
test("missing company, changed account semantics and invalid periods fail closed",()=>{
 assert.throws(()=>compileAnalysis("",emptySelection,fields));
 assert.throws(()=>compileAnalysis("company",{...emptySelection,account:"account"},{...fields,credit_account_id:{kind:"reference",target_type:"Counterparty"}}));
 assert.throws(()=>compileAnalysis("company",{...emptySelection,from:"2025-02-01",to:"2025-01-01"},fields));
 assert.throws(()=>compileAnalysis("company",{...emptySelection,minimum:"1,000"},fields));
});
