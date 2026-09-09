import assert from "node:assert/strict";
import test from "node:test";
import { loadTypeScript } from "./load-typescript.mjs";

const { POST } = await loadTypeScript(new URL("../app/api/ontology/[...path]/route.ts", import.meta.url));
const documentId = `doc_${"a".repeat(64)}`;

function request(body = "{}") {
  const url = `http://local/api/ontology/source-documents/${documentId}/accounting-context/chart-proposal`;
  return Object.assign(new Request(url, {
    method: "POST",
    headers: { authorization: "Bearer scoped" },
    body,
  }), { nextUrl: new URL(url) });
}

function context(route) {
  return { params: Promise.resolve({ path: route.split("/") }) };
}

test("ontology proxy forwards reviewed accounting chart proposals", async (t) => {
  let upstreamUrl = "";
  let upstreamOptions;
  t.mock.method(globalThis, "fetch", async (url, options) => {
    upstreamUrl = String(url);
    upstreamOptions = options;
    return Response.json({ proposal_id: "proposal" }, { status: 202 });
  });

  const response = await POST(request("{\"company_id\":\"seg\"}"), context(`source-documents/${documentId}/accounting-context/chart-proposal`));
  assert.equal(response.status, 202);
  assert.equal(upstreamOptions.method, "POST");
  assert.equal(upstreamOptions.headers.Authorization, "Bearer scoped");
  assert.equal(upstreamOptions.headers["Content-Type"], "application/json");
  assert.equal(Buffer.from(upstreamOptions.body).toString("utf8"), "{\"company_id\":\"seg\"}");
  assert.match(upstreamUrl, /\/v1\/ontology\/source-documents\/doc_a{64}\/accounting-context\/chart-proposal$/);
});

test("ontology proxy still rejects unknown accounting context actions before backend", async (t) => {
  t.mock.method(globalThis, "fetch", () => {
    throw new Error("must not contact backend");
  });
  const response = await POST(request(), context(`source-documents/${documentId}/accounting-context/delete-ledger`));
  assert.equal(response.status, 404);
});
