import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";
import ts from "typescript";
const source=await readFile(new URL("../app/posted-movement-presentation.ts",import.meta.url),"utf8");
const {pairPostingGroups,displayPostedAmount}=await import(`data:text/javascript;base64,${Buffer.from(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText).toString("base64")}`);
test("paired columns retain exact original groups and leave absent sides absent",()=>{
 const debit={account_code:"7310",side:"debit",value:"58988.95000000000001",source_coordinates:["Base!S2"]};
 const credit={account_code:"1210",side:"credit",value:"3",source_coordinates:["Base!S3"]};
 const rows=pairPostingGroups([debit,credit]);
 assert.equal(rows[0].debit,debit);assert.equal(rows[0].credit,undefined);assert.equal(rows[1].credit,credit);
 assert.throws(()=>pairPostingGroups([debit,debit]));
 assert.throws(()=>pairPostingGroups([{...debit,side:"net"}]));
});
test("display rounding retains arbitrary integer precision without changing original evidence",()=>{
 assert.equal(displayPostedAmount("9007199254740993.125"),"9,007,199,254,740,993.13");
 assert.equal(displayPostedAmount("58988.95000000000001"),"58,988.95");
 assert.equal(displayPostedAmount("-0.004"),"-0.00");
 assert.equal(displayPostedAmount("unavailable"),"unavailable");
});
