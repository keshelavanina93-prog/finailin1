import assert from "node:assert/strict";
import test from "node:test";
import { loadTypeScript } from "./load-typescript.mjs";

const context = await loadTypeScript(new URL("../app/dimensional-frontend-context.ts", import.meta.url));

const base = {
  tenantId: "tenant-ge",
  actorId: "analyst-1",
  role: "finance_analyst",
  permissions: ["ontology_read"],
  authorityState: "retained_evidence",
  time: { validAt: "2025-04-30T23:59:59Z", knownAt: "2025-09-09T10:00:00Z" },
};

test("finance exact scope requires company, period, currency, ledger and evidence", () => {
  assert.deepEqual(context.missingScope(base, context.financeScopeRequirements), [
    "company",
    "period",
    "currency",
    "ledger",
    "evidence",
  ]);

  const scoped = {
    ...base,
    companyId: "socargeorgia",
    periodId: "2025-04",
    currencyId: "GEL",
    ledgerId: "statutory",
    evidenceId: "source-evidence",
  };
  assert.deepEqual(context.missingScope(scoped, context.financeScopeRequirements), []);
  assert.equal(context.canRequestExactScope(scoped, context.financeScopeRequirements), true);
});

test("operational exact scope requires source/evidence and valid/known time", () => {
  const scoped = {
    ...base,
    companyId: "sgp",
    sourceId: "orpak-shift-log",
    evidenceId: "sha256",
  };
  assert.deepEqual(context.missingScope(scoped, context.operationalScopeRequirements), []);

  const missingTime = { ...scoped, time: {} };
  assert.deepEqual(context.missingScope(missingTime, context.operationalScopeRequirements), ["valid_at", "known_at"]);
});

test("blocked and refused authority states cannot request even complete exact scope", () => {
  const complete = {
    ...base,
    companyId: "seg",
    periodId: "2025-04",
    currencyId: "GEL",
    ledgerId: "statutory",
    evidenceId: "retained",
  };
  assert.equal(context.canRequestExactScope({ ...complete, authorityState: "blocked" }, context.financeScopeRequirements), false);
  assert.equal(context.canRequestExactScope({ ...complete, authorityState: "refused" }, context.financeScopeRequirements), false);
});

test("context summary preserves missing scope instead of inventing defaults", () => {
  assert.equal(
    context.contextSummary(base),
    "company:unscoped | period:unscoped | currency:unscoped | Retained evidence",
  );
});
