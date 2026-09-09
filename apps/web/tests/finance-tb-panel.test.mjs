import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";

const source=await readFile(new URL("../app/finance-ontology-workspace.tsx",import.meta.url),"utf8");

test("Finance ontology exposes generic source-header TB draft controls",()=>{
 assert.match(source,/call<TBSource\[\]>\("tb\/sources"/);
 assert.match(source,/call<TBDraft>\("tb\/draft"/);
 assert.match(source,/receipt_ids: tbSelected/);
 assert.match(source,/SOURCE HEADER ONLY/);
 assert.match(source,/Current date, session date and ingestion timestamp never set or rewrite the ledger period/);
 assert.match(source,/NOT_CERTIFIED/);
 assert.match(source,/Petroleum actuals are unimplemented/);
 assert.match(source,/TB_Finance_Draft\.zip/);
});
