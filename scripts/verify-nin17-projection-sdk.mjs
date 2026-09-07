// Consume actual Python projections; do not duplicate the SDK response guard.
import assert from "node:assert/strict";
import {createHash} from "node:crypto";
import {readFileSync} from "node:fs";
import {assertProjection} from "../apps/web/app/semantic-analysis-state.ts";

const projections = JSON.parse(readFileSync(0, "utf8"));
assert.equal(projections.length, 3);
for (const projection of projections) {
  assertProjection(projection, projection.request);
  assert.equal(projection.descriptor.contract, "semantic-analysis/2");
  assert.equal(projection.descriptor.measure, null);
  assert.equal(projection.descriptor.visual, "NONE");
  assert.equal(projection.descriptor.row_noun, "objects");
  for (const field of projection.descriptor.fields) {
    assert.equal(field.aggregation, "NONE");
    assert.equal(field.role, field.key === "account" ? "DIMENSION" : "ATTRIBUTE");
  }
}
const [initial, selected, filtered] = projections;
assert.deepEqual(initial.rows.map(row => row.values.net_movement.value).sort(), ["-731.97", "731.97"]);
assert.equal(selected.selection.contributor.coordinate, "Base!S2");
assert.equal(filtered.rows.length, 1);
// Reproduce the frozen candidate's invalid mixed /1 contract: it must be rejected.
const old = structuredClone(initial);
Object.assign(old.descriptor, {contract: "semantic-analysis/1", measure: "net_movement", visual: "HORIZONTAL_BARS", row_noun: "groups"});
Object.assign(old.descriptor.fields.find(field => field.key === "net_movement"), {role: "MEASURE", aggregation: "RETAINED_VALUE_ONLY"});
assert.throws(() => assertProjection(old, old.request));
for (const change of [{measure: "net_movement"}, {visual: "HORIZONTAL_BARS"}]) {
  const invalid = structuredClone(initial);
  Object.assign(invalid.descriptor, change);
  assert.throws(() => assertProjection(invalid, invalid.request));
}
console.log(JSON.stringify({status: "LOCAL_BACKEND_FRONTEND_SDK_PASS", projections: 3,
  negative_contract_checks: 3, browser_verified: false, native_runtime_verified: false,
  sdk_sha256: createHash("sha256").update(readFileSync(new URL("../apps/web/app/semantic-analysis-state.ts", import.meta.url))).digest("hex")}, null, 2));
