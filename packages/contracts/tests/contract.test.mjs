import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("source authority schema is strict and scope-bound", async () => {
  const schemaUrl = new URL("../source-authority.schema.json", import.meta.url);
  const schema = JSON.parse(await readFile(schemaUrl, "utf8"));

  assert.equal(schema.additionalProperties, false);
  assert.deepEqual(schema.properties.scope.required, [
    "tenant_id",
    "legal_entity_id",
    "period",
    "currency",
  ]);
  assert.equal(schema.properties.evidence.minItems, 1);
});
