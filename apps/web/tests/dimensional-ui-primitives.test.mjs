import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

async function loadG8Ui() {
  const root = fileURLToPath(new URL("../.finai/test-modules/", import.meta.url));
  await mkdir(root, { recursive: true });
  const output = await mkdtemp(resolve(root, "dimensional-ui-"));
  let source = await readFile(new URL("../app/g8-ui.tsx", import.meta.url), "utf8");
  source = source
    .replace('"use client";', "")
    .replace('import Image from "next/image";', "function Image(props) { return <img {...props} />; }")
    .replace(
      'import { ArrowRight, WarningCircle, CheckCircle, Clock, LockKey, ShieldCheck, SlidersHorizontal, XCircle } from "@phosphor-icons/react";',
      "function Icon() { return null; } const ArrowRight = Icon, WarningCircle = Icon, CheckCircle = Icon, Clock = Icon, LockKey = Icon, ShieldCheck = Icon, SlidersHorizontal = Icon, XCircle = Icon;",
    );
  const emitted = ts.transpileModule(source, {
    fileName: "g8-ui.tsx",
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
    },
  }).outputText;
  const destination = resolve(output, "g8-ui.mjs");
  await writeFile(destination, emitted);
  return import(pathToFileURL(destination).href);
}

const ui = await loadG8Ui();

test("authority state mapping is deterministic across accepted input forms", () => {
  assert.deepEqual(ui.describeAuthorityState("approved"), {
    code: "APPROVED",
    label: "Approved authority",
    tone: "good",
    detail: "Accepted for governed use.",
  });
  assert.deepEqual(ui.describeAuthorityState("review-required"), {
    code: "REVIEW_REQUIRED",
    label: "Review required",
    tone: "warning",
    detail: "Authority has not been accepted.",
  });
  assert.deepEqual(ui.describeAuthorityState("REFUSED"), {
    code: "REFUSED",
    label: "Authority refused",
    tone: "bad",
    detail: "The system refused to establish authority.",
  });
});

test("refused and unavailable authority do not collapse into empty or zero", () => {
  const refused = ui.describeAuthorityState("REFUSED");
  const unavailable = ui.describeAuthorityState("UNAVAILABLE");
  const empty = ui.describeAuthorityState("");
  const zero = ui.describeAuthorityState(0);

  assert.equal(refused.code, "REFUSED");
  assert.equal(unavailable.code, "UNAVAILABLE");
  assert.equal(empty.code, "EMPTY");
  assert.equal(zero.code, "0");
  assert.notEqual(refused.label, unavailable.label);
  assert.notEqual(unavailable.label, empty.label);
  assert.notEqual(zero.label, empty.label);
});

test("dimensional badges render mapped state and accessible visible labels", () => {
  const refused = renderToStaticMarkup(React.createElement(ui.AuthorityBadge, { value: "REFUSED" }));
  assert.match(refused, /data-state="REFUSED"/);
  assert.match(refused, /Authority refused/);

  const unavailable = renderToStaticMarkup(React.createElement(ui.EvidenceBadge, { value: "UNAVAILABLE" }));
  assert.match(unavailable, /data-state="UNAVAILABLE"/);
  assert.match(unavailable, /Evidence unavailable/);

  const gate = renderToStaticMarkup(React.createElement(ui.GateBadge, { value: "PASS" }));
  assert.match(gate, /data-state="PASS"/);
  assert.match(gate, /Gate passed/);
});

test("scope, time and refusal primitives distinguish absence from refused state", () => {
  const scoped = renderToStaticMarkup(React.createElement(ui.ScopeChip, { label: "Company", value: "SGC" }));
  assert.match(scoped, /Company/);
  assert.match(scoped, /SGC/);

  const time = renderToStaticMarkup(React.createElement(ui.TimeBadge, { value: null }));
  assert.match(time, /unavailable/);
  assert.match(time, /Time unavailable/);

  const refusal = renderToStaticMarkup(React.createElement(ui.RefusalState, null, "This command was refused by policy."));
  assert.match(refusal, /role="status"/);
  assert.match(refusal, /Request refused/);
  assert.match(refusal, /This command was refused by policy/);
});
