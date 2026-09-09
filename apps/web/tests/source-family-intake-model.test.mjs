import assert from "node:assert/strict";
import test from "node:test";
import { loadTypeScript } from "./load-typescript.mjs";

const model = await loadTypeScript(new URL("../app/source-family-intake-model.ts", import.meta.url));

test("source family intake model covers requested massive multi-entity sources", () => {
  assert.deepEqual(
    model.SOURCE_FAMILY_INTAKE_PLANS.map((family) => family.id),
    [
      "1c_trial_balance",
      "1c_journal_movements",
      "seg_procurement_expense",
      "socar_sgp_seg_multi_entity",
      "orpak_forecourt_pos",
      "gas_telemetry",
      "retail_cash_registers",
      "regulatory_external_evidence",
    ],
  );

  for (const family of model.SOURCE_FAMILY_INTAKE_PLANS) {
    assert.ok(family.systems.length > 0, family.id);
    assert.ok(family.requiredScopeDimensions.length > 0, family.id);
    assert.ok(family.requiredEvidence.length > 0, family.id);
    assert.ok(Array.isArray(family.routes.proxyRoutes), family.id);
    assert.ok(Array.isArray(family.routes.backendRoutes), family.id);
    assert.ok(["wired", "proxy-only", "planned"].includes(family.routes.status), family.id);
    assert.ok(["implemented", "partially-implemented", "target-only"].includes(family.currentImplementationStatus), family.id);
    assert.ok(Array.isArray(family.blockedOrMissingContracts), family.id);
  }
});

test("classification separates anchored, partial and target-only families", () => {
  const trialBalance = model.sourceFamilyById("1c_trial_balance");
  const forecourt = model.sourceFamilyById("orpak_forecourt_pos");
  assert.equal(model.classifySourceFamily(trialBalance), "partial");
  assert.equal(model.classifySourceFamily(forecourt), "target-only");

  const anchored = {
    ...trialBalance,
    implementedScopeDimensions: [...trialBalance.requiredScopeDimensions],
    presentEvidence: [...trialBalance.requiredEvidence],
    currentImplementationStatus: "implemented",
    blockedOrMissingContracts: [],
  };
  assert.equal(model.classifySourceFamily(anchored), "anchored");

  const targetOnlyFromPlannedRoute = {
    ...trialBalance,
    routes: { ...trialBalance.routes, status: "planned" },
    currentImplementationStatus: "target-only",
  };
  assert.equal(model.classifySourceFamily(targetOnlyFromPlannedRoute), "target-only");
});

test("missing dimensions are returned for analyst-facing UI without mutating the catalogue", () => {
  assert.deepEqual(model.missingDimensionsForAnalyst("1c_trial_balance"), ["subaccount"]);
  assert.deepEqual(model.missingDimensionsForAnalyst("orpak_forecourt_pos"), [
    "pump",
    "fuel_grade",
    "shift",
    "operator",
    "lineage",
  ]);
  assert.deepEqual(model.missingDimensionsForAnalyst("unknown-family"), []);

  const before = model.sourceFamilyById("1c_trial_balance").implementedScopeDimensions;
  model.missingDimensionsForAnalyst("1c_trial_balance");
  assert.equal(model.sourceFamilyById("1c_trial_balance").implementedScopeDimensions, before);
});

test("summary keeps completion distinct from planning coverage", () => {
  assert.deepEqual(model.sourceFamilyIntakeSummary(), {
    families: 8,
    anchored: 0,
    partial: 5,
    targetOnly: 3,
  });
});
