import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source=await readFile(new URL("../app/definition-restoration-time.ts",import.meta.url),"utf8");
const {restorationInstant}=await import(`data:text/javascript;base64,${Buffer.from(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText).toString("base64")}`);

test("restoration comparison preserves adjacent microseconds and equivalent timezone offsets",()=>{
  assert.equal(restorationInstant("2026-09-07T18:29:53.827310+04:00"),"2026-09-07T14:29:53.827310Z");
  assert.equal(restorationInstant("2026-09-07T14:29:53.82731Z"),"2026-09-07T14:29:53.827310Z");
  assert.notEqual(restorationInstant("2026-09-07T14:29:53.123001Z"),restorationInstant("2026-09-07T14:29:53.123999Z"));
  assert.equal(restorationInstant("2024-03-01T00:15:00+00:30"),"2024-02-29T23:45:00.000000Z");
});

test("restoration input refuses calendar normalization, ambiguous time and precision loss",()=>{
  for(const value of ["2025-02-29T00:00:00Z","2026-04-31T00:00:00Z","2026-09-07T24:00:00Z","2026-09-07T14:29:60Z","2026-09-07T14:29:53","2026-09-07T14:29:53.1234567Z","2026-09-07T14:29:53+00:99","0001-01-01T00:00:00+04:00",null])assert.equal(restorationInstant(value),null,String(value));
});
