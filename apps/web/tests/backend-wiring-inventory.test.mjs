import assert from "node:assert/strict";
import test from "node:test";
import { loadTypeScript } from "./load-typescript.mjs";

const inventory = await loadTypeScript(new URL("../app/backend-wiring-inventory.ts", import.meta.url));

test("enumerates frontend proxy families and their mapped backend families", () => {
  const expected = new Map([
    ["workspace", ["/api/workspace", "/v1/workspace"]],
    ["ontology", ["/api/ontology", "/v1/ontology"]],
    ["operations", ["/api/operations", "/v1/operations"]],
    ["diagnostics", ["/api/diagnostics", "/v1/diagnostics"]],
    ["hydration", ["/api/hydration", "/v1/hydration"]],
    ["readiness", ["/api/readiness", "/ready"]],
  ]);

  for (const [id, [nextProxyFamily, fastApiFamily]] of expected) {
    const family = inventory.routeFamilyById(id);
    assert.ok(family, `${id} route family is present`);
    assert.equal(family.nextProxyFamily, nextProxyFamily);
    assert.equal(family.fastApiFamily, fastApiFamily);
    assert.ok(family.wiredRoutes.length > 0, `${id} retains at least one exact wired route`);
  }
});

test("pure listing helpers keep wired, partial and target-only route families separate", () => {
  assert.deepEqual(inventory.listStronglyWiredRouteFamilies().map((family) => family.id), [
    "ontology",
    "diagnostics",
    "hydration",
    "readiness",
  ]);
  assert.deepEqual(inventory.listPartialRouteFamilies().map((family) => family.id), ["workspace", "operations"]);
  assert.deepEqual(inventory.listTargetOnlyRouteFamilies().map((family) => family.id), [
    "planning",
    "top_level_reporting",
    "nyx_reasoning",
    "outcomes_learning",
    "petroleum_telemetry_bridge",
  ]);
});

test("disabled or target-only dimensions cannot be counted as backend wired", () => {
  const targetOnly = inventory.listTargetOnlyRouteFamilies();
  assert.ok(targetOnly.every((family) => family.nextProxyFamily === null));
  assert.ok(targetOnly.every((family) => family.fastApiFamily === null));
  assert.ok(targetOnly.every((family) => family.wiredRoutes.length === 0));
  assert.deepEqual(targetOnly.flatMap((family) => family.targetOnlyDimensions), [
    "planning",
    "top-level reporting",
    "NYX reasoning",
    "outcomes/learning",
    "full petroleum telemetry bridge",
  ]);
});

test("chart proposal is included as a strongly wired ontology route", () => {
  const ontology = inventory.routeFamilyById("ontology");
  assert.equal(ontology.status, "strongly_wired");
  assert.equal(inventory.isChartProposalWired(), true);
  assert.ok(
    ontology.wiredRoutes.includes(
      "/api/ontology/source-documents/*/accounting-context/chart-proposal -> /v1/ontology/source-documents/*/accounting-context/chart-proposal",
    ),
  );
});
