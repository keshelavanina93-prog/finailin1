import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("operator shell exposes all epistemic states", async () => {
  const source = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");

  for (const state of ["OBSERVED", "DERIVED", "INFERRED", "UNAVAILABLE"]) {
    assert.match(source, new RegExp(`state: "${state}"`));
  }
  assert.match(source, /promotion requires reconciliation and approval/i);
});
