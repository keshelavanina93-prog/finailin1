import assert from "node:assert/strict";
import test from "node:test";
import { loadTypeScript } from "./load-typescript.mjs";

const contract = await loadTypeScript(new URL("../app/dimensional-frontend-contract.ts", import.meta.url));

test("dimensional frontend contract defines all governing axes", () => {
  assert.equal(contract.DIMENSIONAL_AXES.length, 14);
  assert.deepEqual(contract.DIMENSIONAL_AXES, [
    "product_mode",
    "user_role",
    "business_scope",
    "financial_scope",
    "operational_scope",
    "evidence_state",
    "authority_state",
    "time_state",
    "interaction_projection",
    "runtime_state",
    "backend_contract_state",
    "trust_zone",
    "decision_state",
    "acceptance_gate",
  ]);
});

test("massive intake, accounting, finance and operations surfaces are mapped to backend route families", () => {
  const source = contract.surfaceById("source_evidence_intake");
  assert.ok(source.proxyRoutes.includes("/api/hydration"));
  assert.ok(source.backendRoutes.includes("/v1/hydration/ingest"));
  assert.ok(source.backendRoutes.includes("/v1/ontology/source-documents/*"));

  const accounting = contract.surfaceById("accounting_dimensions");
  assert.ok(accounting.proxyRoutes.includes("/api/ontology/account-dimension-policy"));
  assert.ok(accounting.backendRoutes.includes("/v1/ontology/account-dimension-policy"));
  assert.ok(accounting.axes.includes("financial_scope"));

  const finance = contract.surfaceById("finance_ledger");
  assert.ok(finance.proxyRoutes.includes("/api/hydration/package"));
  assert.ok(finance.backendRoutes.includes("/v1/hydration/trial-balance-package"));

  const operations = contract.surfaceById("operations_physical_graph");
  assert.ok(operations.proxyRoutes.includes("/api/operations/*"));
  assert.ok(operations.axes.includes("operational_scope"));
});

test("partial dimensions cannot be reported as fully wired", () => {
  assert.equal(contract.isFullyWired("nyx_reasoning"), false);
  assert.equal(contract.isFullyWired("outcomes_learning"), false);
  assert.ok(contract.missingWiringEvidence("outcomes_learning").includes("browser_proof"));
  assert.ok(contract.missingWiringEvidence("outcomes_learning").includes("restart_readback"));
});

test("coverage summary separates partial implementation from completion", () => {
  const summary = contract.dimensionalCoverageSummary();
  assert.equal(summary.axes, 14);
  assert.equal(summary.surfaces, 8);
  assert.equal(summary.fullyWired, 0);
  assert.ok(summary.partial > 0);
  assert.equal(summary.targetOnly, 0);
});
